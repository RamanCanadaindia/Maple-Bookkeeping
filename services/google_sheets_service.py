import os
import json
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials
import pandas as pd


def _google_credentials(scopes):
    """Load a service account locally or from Streamlit Cloud secrets."""
    try:
        if "google_service_account" in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["google_service_account"]), scopes=scopes
            )
    except FileNotFoundError:
        pass

    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        return Credentials.from_service_account_info(
            json.loads(credentials_json), scopes=scopes
        )

    credentials_path = "google_credentials.json"
    if os.path.exists(credentials_path):
        return Credentials.from_service_account_file(credentials_path, scopes=scopes)

    raise RuntimeError(
        "Google Sheets is not configured. Add [google_service_account] to Streamlit secrets."
    )


def google_credentials_configured() -> bool:
    try:
        if "google_service_account" in st.secrets:
            return True
    except FileNotFoundError:
        pass
    return bool(os.getenv("GOOGLE_CREDENTIALS_JSON")) or os.path.exists("google_credentials.json")

def upload_dataframe_to_google_sheets(df: pd.DataFrame, master_title: str, tab_title: str, share_email: str = None) -> str:
    """
    Uploads a pandas DataFrame to a specific tab (worksheet) inside a single master Google Spreadsheet.
    Opens the existing spreadsheet shared with the Service Account.
    """
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds = _google_credentials(scopes)
    service_account_email = creds.service_account_email
    client = gspread.authorize(creds)
    
    # 1. Open the master spreadsheet
    try:
        sh = client.open(master_title)
    except gspread.SpreadsheetNotFound:
        raise Exception(
            f"Consolidated Sheet '{master_title}' not found or not shared with the service account.\n\n"
            f"👉 Please follow these two quick steps:\n"
            f"1. Create a Google Sheet named **'{master_title}'** in your personal Google Drive.\n"
            f"2. Click the 'Share' button in that Google Sheet and share it with this email address as an **Editor**:\n"
            f"**`{service_account_email}`**"
        )
            
    # 2. Open or create the client-specific tab (worksheet)
    tab_title_clean = tab_title[:95] if tab_title else "Sheet1"
    
    try:
        worksheet = sh.worksheet(tab_title_clean)
        worksheet.clear()
    except gspread.WorksheetNotFound:
        # Check if the spreadsheet has only the default "Sheet1" that is empty; if so, we can rename it
        worksheets = sh.worksheets()
        if len(worksheets) == 1 and worksheets[0].title == "Sheet1":
            worksheet = worksheets[0]
            worksheet.update_title(tab_title_clean)
            worksheet.clear()
        else:
            worksheet = sh.add_worksheet(title=tab_title_clean, rows="1000", cols="25")
            
    # 3. Clean and format the data
    df_clean = df.copy()
    for col in df_clean.columns:
        if pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            df_clean[col] = df_clean[col].dt.strftime("%Y-%m-%d")
            
    df_clean = df_clean.fillna("")
    data = [df_clean.columns.tolist()] + df_clean.values.tolist()
    
    # 4. Update the worksheet
    worksheet.update(values=data, range_name="A1")
    
    # 5. Format headers nicely
    worksheet.format("A1:Z1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
    })
    
    return sh.url
