import re

def clean_description(raw_desc: str) -> str:
    """
    Normalizes bank/credit card description strings to isolate the merchant name.
    Example: "POS PURCHASE 4930129 TIM HORTONS #4928 SURREY BC" => "TIM HORTONS"
    """
    if not raw_desc:
        return "UNKNOWN MERCHANT"
        
    cleaned = raw_desc.upper().strip()
    
    # 1. Remove common transaction prefixes
    prefixes = [
        r'\bPOS\s+PURCHASE\b', r'\bPOS\s+PUR\b', r'\bPOS\b', 
        r'\bDEBIT\s+PURCHASE\b', r'\bDIRECT\s+DEB\b', r'\bDEBIT\b', r'\bDEB\b', 
        r'\bPREAUTH\b', r'\bPRE-AUTH\b', 
        r'\bINTERAC\s+PURCHASE\b', r'\bINTERAC\s+PUR\b', r'\bINTERAC\b',
        r'\bE-TRANSFER\b', r'\bE-TRANS\b', r'\bE-PMT\b', 
        r'\bWITHDRAWAL\b', r'\bDEPOSIT\b', r'\bPURCHASE\b', r'\bPURCH\b', r'\bPUR\b', r'\bPMT\b', 
        r'\bPAYMENT\b', r'\bONLINE\s+PMT\b', r'\bMOBILE\s+PMT\b',
        r'\bINTERNET\s+TRANSFER\b', r'\bEMAIL\s+TRANSFER\b'
    ]
    for p in prefixes:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)

    # 2. Remove reference numbers, transaction codes, card sequences (numbers 6+ digits long)
    cleaned = re.sub(r'\b\d{6,}\b', '', cleaned)
    cleaned = re.sub(r'#\s*\d+', '', cleaned)
    cleaned = re.sub(r'\*\d{4,}', '', cleaned)  # Card mask like *1234
    
    # 3. Remove common Canadian geographic identifiers at the end of descriptions
    # Matches common cities followed by provincial suffix (BC, AB, ON, QC, etc.)
    provinces = r'\b(?:BC|AB|ON|QC|MB|SK|NS|NB|NL|PE|YT|NT|NU)\b'
    cities = r'\b(?:SURREY|VANCOUVER|BURNABY|RICHMOND|COQUITLAM|DELTA|LANGLEY|ABBOTSFORD|VICTORIA|NANAIMO|KELOWNA|CALGARY|EDMONTON|TORONTO|OTTAWA|MISSISSAUGA|MONTREAL)\b'
    
    cleaned = re.sub(rf'{cities}\s+{provinces}', '', cleaned)
    cleaned = re.sub(provinces, '', cleaned)
    
    # 4. Remove bank machine specific references (e.g. ATM, W/D, FT, etc.)
    cleaned = re.sub(r'\b(?:ATM|W/D|FT|MB-W/D|IB|TF)\b', '', cleaned)
    
    # 5. Clean special punctuation characters
    cleaned = re.sub(r'[\-\:\,\/]+', ' ', cleaned)
    
    # 6. Compress multiple whitespaces
    cleaned = " ".join(cleaned.split())
    
    # Fallback to original stripped uppercase if empty after cleaning
    if not cleaned:
        cleaned = " ".join(raw_desc.upper().split())
        
    return cleaned.strip()
