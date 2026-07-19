import requests
import json
import base64
import io
import pypdf
from services.ai_service import _get_gemini_api_key

def parse_receipt_file(file_bytes: bytes, mime_type: str) -> dict:
    """
    Sends receipt image or PDF text to Gemini 2.5 Pro to extract transaction details.
    """
    gemini_api_key = _get_gemini_api_key()
    if not gemini_api_key:
        raise RuntimeError("Gemini is not configured. Add GEMINI_API_KEY to Streamlit secrets.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={gemini_api_key}"
    
    prompt = """
    Analyze this receipt. Extract the following details into structured JSON:
    - date (String formatted as YYYY-MM-DD, default null)
    - merchant (String, default null)
    - amount (Number representing total transaction amount, default 0.0)
    - gst (Number representing GST portion of amount, default 0.0)
    
    If you cannot read a field, return null or 0.0.
    """
    
    # 1. Structure payload parts based on mime-type
    parts = [{"text": prompt}]
    
    if "pdf" in mime_type.lower():
        # PDF: Extract text first
        pdf_text = ""
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pdf_text += t
            parts.append({"text": f"Receipt PDF Text content:\n{pdf_text}"})
        except:
            return _local_receipt_fallback()
    else:
        # Image: Send base64 inlineData
        b64_data = base64.b64encode(file_bytes).decode("utf-8")
        parts.append({
            "inlineData": {
                "mimeType": mime_type,
                "data": b64_data
            }
        })
        
    payload = {
        "contents": [
            {
                "parts": parts
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "date": {"type": "STRING"},
                    "merchant": {"type": "STRING"},
                    "amount": {"type": "NUMBER"},
                    "gst": {"type": "NUMBER"}
                },
                "required": ["date", "merchant", "amount", "gst"]
            }
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code == 200:
            result = response.json()
            text_resp = result['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_resp)
            return {
                "date": data.get("date", None),
                "merchant": data.get("merchant", None),
                "amount": float(data.get("amount", 0.0)),
                "gst": float(data.get("gst", 0.0))
            }
        else:
            return _local_receipt_fallback()
    except:
        return _local_receipt_fallback()

def _local_receipt_fallback() -> dict:
    """
    Fallback receipt data if the Gemini OCR service times out.
    """
    return {
        "date": None,
        "merchant": "Receipt Doc",
        "amount": 0.0,
        "gst": 0.0
    }
