import json
import os

import requests
import streamlit as st


def _get_gemini_api_key() -> str:
    """Read the Gemini key from Streamlit secrets or the environment."""
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except (FileNotFoundError, KeyError):
        return os.getenv("GEMINI_API_KEY", "")

# Standard Chart of Accounts Categories for Canadian Bookkeeping
VALID_CATEGORIES = [
    "Sales Revenue",
    "Auto Fuel",
    "Meals & Entertainment",
    "Office Supplies",
    "Office Expense",
    "Advertising",
    "Rent",
    "Insurance",
    "Subcontractors",
    "Bank Fees",
    "Taxes & Licenses",
    "Opening Balance Equity",
    "Due to Related Party",
    "Repairs & Maintenance",
    "Equipment Rental",
    "Bank Transfer",
    "Parking",
    "Travel Expense",
    "Suspense Expense"
]

def suggest_merchant_category(merchant_name: str) -> dict:
    """
    Calls Gemini 2.5 Pro to suggest the best accounting category for a merchant.
    Returns dictionary with: category, confidence, and explanation.
    """
    if not merchant_name:
        return {"category": "Suspense Expense", "confidence": 1.0}
        
    gemini_api_key = _get_gemini_api_key()
    if not gemini_api_key:
        return _local_heuristic_suggest(merchant_name)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={gemini_api_key}"
    
    prompt = f"""
    You are an expert Canadian CPA bookkeeping bot.
    Classify the following merchant name into exactly one of these categories:
    {json.dumps(VALID_CATEGORIES)}
    
    Merchant Name: "{merchant_name}"
    
    Provide a structured JSON output with the category chosen, confidence (0.0 to 1.0), and a brief 1-sentence reason.
    """
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "category": {
                        "type": "STRING",
                        "enum": VALID_CATEGORIES
                    },
                    "confidence": {
                        "type": "NUMBER"
                    },
                    "explanation": {
                        "type": "STRING"
                    }
                },
                "required": ["category", "confidence", "explanation"]
            }
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=8)
        if response.status_code == 200:
            result = response.json()
            # Extract structured output from parts text
            text_resp = result['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_resp)
            return {
                "category": data.get("category", "Suspense Expense"),
                "confidence": float(data.get("confidence", 0.5)),
                "explanation": data.get("explanation", "")
            }
        else:
            # Fallback to local heuristic matching if API fails
            return _local_heuristic_suggest(merchant_name)
    except:
        return _local_heuristic_suggest(merchant_name)

def _local_heuristic_suggest(merchant_name: str) -> dict:
    """
    Local fallback classifier if the Gemini API is offline or times out.
    """
    m_upper = merchant_name.upper()
    
    if "TIM HORTONS" in m_upper or "STARBUCKS" in m_upper or "RESTAURANT" in m_upper or "FOOD" in m_upper or "CAFE" in m_upper:
        return {"category": "Meals & Entertainment", "confidence": 0.9, "explanation": "Matched eating establishment keyword."}
    elif "SHELL" in m_upper or "HUSKY" in m_upper or "PETRO" in m_upper or "CHEVRON" in m_upper or "GAS" in m_upper or "FUEL" in m_upper:
        return {"category": "Auto Fuel", "confidence": 0.9, "explanation": "Matched gas station brand keyword."}
    elif "OFFICE" in m_upper or "STAPLES" in m_upper or "AMAZON" in m_upper or "PAPER" in m_upper:
        return {"category": "Office Supplies", "confidence": 0.8, "explanation": "Matched retail supplier keyword."}
    elif "FACEBOOK" in m_upper or "GOOGLE" in m_upper or "ADWORDS" in m_upper or "ADS" in m_upper or "FLYER" in m_upper:
        return {"category": "Advertising", "confidence": 0.9, "explanation": "Matched advertising provider keyword."}
    elif "INTEREST" in m_upper or "FEE" in m_upper or "CHARGE" in m_upper or "RBC" in m_upper or "TD" in m_upper or "BANK" in m_upper:
        return {"category": "Bank Fees", "confidence": 0.8, "explanation": "Matched financial institution charge keyword."}
        
    return {"category": "Suspense Expense", "confidence": 0.5, "explanation": "Unrecognized merchant, mapped to suspense."}
