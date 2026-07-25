import base64
import json
import os
import time
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from cryptography.fernet import Fernet

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
MAX_ATTACHMENT_SIZE_MB = 20  # Safe threshold below Gmail's 25MB limit

# Secure encryption helpers
def get_encryption_key():
    key = None
    try:
        key = st.secrets.get("TOKEN_ENCRYPTION_KEY")
    except Exception:
        pass
    if not key:
        key = os.getenv("TOKEN_ENCRYPTION_KEY")
    return key

def encrypt_token(token_str: str) -> str:
    key = get_encryption_key()
    if not key:
        return token_str
    try:
        f = Fernet(key.encode())
        return f.encrypt(token_str.encode()).decode()
    except Exception as e:
        print(f"[Encryption Error] {e}")
        return token_str

def decrypt_token(encrypted_str: str) -> str:
    key = get_encryption_key()
    if not key:
        return encrypted_str
    try:
        f = Fernet(key.encode())
        return f.decrypt(encrypted_str.encode()).decode()
    except Exception as e:
        print(f"[Decryption Error] {e}")
        return encrypted_str

# OAuth 2.0 Web Flow Helpers
def get_oauth_flow(redirect_uri: str):
    """
    Creates a Web flow client using credentials from secrets.
    """
    try:
        client_id = st.secrets.get("GOOGLE_CLIENT_ID")
        client_secret = st.secrets.get("GOOGLE_CLIENT_SECRET")
    except Exception:
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in configurations.")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )

def exchange_code(flow, code: str) -> dict:
    """
    Exchanges auth code for OAuth token dictionary.
    """
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    }

def get_gmail_service(token_json_str: str):
    """
    Loads and refreshes credentials to initialize the Gmail API service client.
    """
    decrypted = decrypt_token(token_json_str)
    token_info = json.loads(decrypted)
    
    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri=token_info.get("token_uri"),
        client_id=token_info.get("client_id"),
        client_secret=token_info.get("client_secret"),
        scopes=token_info.get("scopes")
    )
    
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed credentials
            token_info["token"] = creds.token
            token_json_str = encrypt_token(json.dumps(token_info))
            
    service = build('gmail', 'v1', credentials=creds)
    return service, token_json_str

def send_gmail_email(service, to_email: str, subject: str, body_html: str, cc: str = None, bcc: str = None, reply_to: str = None, attachments: list = None) -> str:
    """
    Sends email via Gmail API with rate-limit retries (exponential backoff: 1s, 5s, 15s).
    attachments is a list of tuples: (file_bytes, filename)
    """
    # Recipient validation
    if not to_email or "@" not in to_email:
        raise ValueError(f"Invalid recipient email address: '{to_email}'")

    message = MIMEMultipart('alternative')
    message['to'] = to_email.strip()
    message['subject'] = subject.strip()
    
    if cc:
        message['cc'] = cc.strip()
    if bcc:
        message['bcc'] = bcc.strip()
    if reply_to:
        message['reply-to'] = reply_to.strip()
        
    # Standard text alternative
    text_fallback = "Please open this email in an HTML-compatible client to view your reminders."
    message.attach(MIMEText(text_fallback, 'plain'))
    
    # HTML content
    message.attach(MIMEText(body_html, 'html'))
    
    # Handle attachments
    if attachments:
        total_size_bytes = sum(len(f_bytes) for f_bytes, _ in attachments)
        if total_size_bytes > MAX_ATTACHMENT_SIZE_MB * 1024 * 1024:
            raise ValueError(f"Total attachment size ({total_size_bytes / 1024 / 1024:.2f}MB) exceeds the {MAX_ATTACHMENT_SIZE_MB}MB limit.")

        for file_bytes, filename in attachments:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(file_bytes)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            message.attach(part)
            
    # Base64url encoding
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    body = {'raw': raw_message}
    
    # Backoff retries for API limits
    retries = [1, 5, 15]
    for attempt, delay in enumerate(retries):
        try:
            sent_msg = service.users().messages().send(userId='me', body=body).execute()
            return sent_msg['id']
        except Exception as e:
            if attempt == len(retries) - 1:
                raise e
            time.sleep(delay)
    
    raise RuntimeError("Failed to send email after retry attempts.")

# Approved Template Variable List
APPROVED_VARS = [
    "client_name", "business_name", "period_start", "period_end",
    "due_date", "reminder_type", "staff_name", "company_name", "phone", "email"
]

def parse_template(template_str: str, variables_dict: dict) -> str:
    """
    Interpolates template variables. Aborts/raises error if any variable is missing.
    """
    parsed = str(template_str)
    
    # Find all variables in template in format {{var}}
    import re
    vars_found = re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', template_str)
    
    for v in vars_found:
        if v not in APPROVED_VARS:
            raise ValueError(f"Template contains unapproved or invalid variable: '{{{{{v}}}}}'")
        if v not in variables_dict or variables_dict[v] is None:
            raise ValueError(f"Missing required template variable value for: '{{{{{v}}}}}'")
            
        parsed = parsed.replace(f"{{{{{v}}}}}", str(variables_dict[v]))
        
    return parsed

# Interface / Extension point classes
class BaseNotificationChannel:
    def send(self, to_address: str, subject: str, body: str, **kwargs) -> str:
        raise NotImplementedError()

class GmailNotificationChannel(BaseNotificationChannel):
    def __init__(self, service):
        self.service = service
        
    def send(self, to_address: str, subject: str, body: str, **kwargs) -> str:
        return send_gmail_email(
            service=self.service,
            to_email=to_address,
            subject=subject,
            body_html=body,
            cc=kwargs.get("cc"),
            bcc=kwargs.get("bcc"),
            reply_to=kwargs.get("reply_to"),
            attachments=kwargs.get("attachments")
        )
