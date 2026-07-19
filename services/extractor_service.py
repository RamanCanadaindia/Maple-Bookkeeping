import re
import csv
import io
import pandas as pd
from datetime import datetime
import pdfplumber
from services.cleaner_service import clean_description

def clean_amount_str(val_str: str) -> float:
    if not val_str:
        return 0.0
    val_clean = val_str.strip()
    is_negative = False
    
    # Check for parentheses indicating negative financial value, e.g. (11,406.53)
    if (val_clean.startswith('(') and val_clean.endswith(')')) or val_clean.startswith('-') or val_clean.endswith('-'):
        is_negative = True
        
    # Strip everything except digits and decimal point
    cleaned = re.sub(r'[^\d\.]', '', val_clean)
    if not cleaned:
        return 0.0
        
    val_float = float(cleaned)
    return -val_float if is_negative else val_float

def parse_csv_statement(file_bytes: bytes) -> list:
    """
    Parses a CSV bank statement and maps columns automatically.
    """
    content = file_bytes.decode("utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    
    if not rows:
        return []
        
    # Auto-detect headers in first few rows
    header_idx = 0
    date_col = -1
    desc_col = -1
    amount_col = -1
    debit_col = -1
    credit_col = -1
    bal_col = -1
    
    # Simple header detection heuristic
    for idx, r in enumerate(rows[:10]):
        row_lower = [str(x).lower().strip() for x in r]
        if any(h in row_lower for h in ["date", "transaction date", "posting date"]):
            header_idx = idx
            break
            
    header_row = [str(x).lower().strip() for x in rows[header_idx]]
    for idx, h in enumerate(header_row):
        if "date" in h:
            date_col = idx
        elif "description" in h or "memo" in h or "detail" in h or "particulars" in h or "name" in h:
            desc_col = idx
        elif "amount" in h or "value" in h:
            amount_col = idx
        elif "debit" in h or "withdrawal" in h or "out" in h:
            debit_col = idx
        elif "credit" in h or "deposit" in h or "in" in h:
            credit_col = idx
        elif "balance" in h:
            bal_col = idx
            
    extracted = []
    for r in rows[header_idx + 1:]:
        if not r or len(r) <= max(date_col, desc_col):
            continue
            
        raw_date = r[date_col]
        raw_desc = r[desc_col]
        
        # Skip empty date/desc
        if not raw_date or not raw_desc:
            continue
            
        # Parse amount
        debit_val = 0.0
        credit_val = 0.0
        amount_val = 0.0
        bal_val = 0.0
        
        if amount_col != -1 and amount_col < len(r) and r[amount_col]:
            try:
                amount_val = clean_amount_str(r[amount_col])
                if amount_val < 0:
                    debit_val = abs(amount_val)
                else:
                    credit_val = amount_val
            except:
                pass
        else:
            if debit_col != -1 and debit_col < len(r) and r[debit_col]:
                try:
                    debit_val = abs(clean_amount_str(r[debit_col]))
                    amount_val = -debit_val
                except:
                    pass
            if credit_col != -1 and credit_col < len(r) and r[credit_col]:
                try:
                    credit_val = abs(clean_amount_str(r[credit_col]))
                    amount_val = credit_val
                except:
                    pass
                    
        if bal_col != -1 and bal_col < len(r) and r[bal_col]:
            try:
                bal_val = float(re.sub(r'[^\d\.]', '', r[bal_col]))
            except:
                pass
                
        # Parse date formats: YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, etc.
        parsed_date = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d-%b-%y"):
            try:
                parsed_date = datetime.strptime(raw_date.strip(), fmt)
                break
            except:
                pass
                
        if not parsed_date:
            continue # Skip invalid rows that don't have a parseable date
            
        extracted.append({
            "date": parsed_date,
            "original_description": raw_desc.strip(),
            "cleaned_description": clean_description(raw_desc),
            "debit": debit_val,
            "credit": credit_val,
            "amount": amount_val,
            "balance": bal_val,
            "ref_number": None
        })
        
    return extracted

def parse_pdf_statement(file_bytes: bytes) -> list:
    """
    Parses a PDF bank statement using pdfplumber to extract transaction tables.
    """
    # Attempt high-fidelity bank statement extraction first using local_extractor
    try:
        from services.local_extractor import detect_bank, extract_digital_pdf
        pdf_stream = io.BytesIO(file_bytes)
        bank_name = detect_bank(pdf_stream)
        
        if bank_name in ["RBC", "TD", "BMO", "CIBC", "Tangerine", "Vancity"]:
            txs, op_bal = extract_digital_pdf(pdf_stream, bank_name)
            extracted = []
            for tx in txs:
                debit_val = float(tx.get("debit") or 0.0)
                credit_val = float(tx.get("credit") or 0.0)
                amount_val = credit_val if credit_val > 0 else -debit_val
                
                tx_date = tx["date"]
                if isinstance(tx_date, str):
                    try:
                        tx_date = datetime.strptime(tx_date, "%Y-%m-%d")
                    except:
                        tx_date = datetime.now()
                        
                extracted.append({
                    "date": tx_date,
                    "original_description": tx["description"],
                    "cleaned_description": clean_description(tx["description"]),
                    "debit": debit_val,
                    "credit": credit_val,
                    "amount": amount_val,
                    "balance": float(tx.get("balance") or 0.0),
                    "ref_number": None
                })
            if extracted:
                return extracted
    except Exception as e:
        print(f"[ExtractorService] Specialized parser fallback: {e}")

    extracted = []
    
    # Common regex to find date patterns (e.g. "Jun 12", "12/06/2026")
    date_regex = re.compile(
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b|\b\d{4}[-/]\d{2}[-/]\d{2}\b|\b\d{2}[-/]\d{2}[-/]\d{4}\b',
        re.IGNORECASE
    )
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            # Try to extract tables first
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Clean None values
                    row_clean = [str(x).strip() for x in row if x is not None]
                    if not row_clean or len(row_clean) < 3:
                        continue
                        
                    # Check if first cell contains a date
                    if date_regex.search(row_clean[0]):
                        raw_date = row_clean[0]
                        # Look for description
                        raw_desc = ""
                        for cell in row_clean[1:]:
                            if len(cell) > 4 and not re.match(r'^\$?\d+', cell):
                                raw_desc = cell
                                break
                                
                        if not raw_desc:
                            raw_desc = row_clean[1]
                            
                        # Search for money values in row cells
                        amounts = []
                        for cell in row_clean[1:]:
                            # Match floating numbers, currency signs
                            num_match = re.search(r'\-?\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?', cell)
                            if num_match:
                                val_str = re.sub(r'[^\d\.\-]', '', num_match.group(0))
                                try:
                                    amounts.append(float(val_str))
                                except:
                                    pass
                                    
                        debit_val = 0.0
                        credit_val = 0.0
                        amount_val = 0.0
                        bal_val = 0.0
                        
                        if len(amounts) >= 1:
                            amount_val = amounts[0]
                            if amount_val < 0:
                                debit_val = abs(amount_val)
                            else:
                                credit_val = amount_val
                        if len(amounts) >= 2:
                            # If second value exists, it might be the balance or credit
                            bal_val = amounts[-1]
                            
                        parsed_date = None
                        for fmt in ("%b %d", "%b %d, %Y", "%d %b", "%Y-%m-%d", "%d/%m/%Y"):
                            try:
                                # Standardize date parser (prepend current year if missing)
                                date_str = raw_date
                                if len(raw_date.split()) == 2 and not any(char.isdigit() and len(word) == 4 for word in raw_date.split() for char in word):
                                    date_str = f"{raw_date} {datetime.utcnow().year}"
                                    parsed_date = datetime.strptime(date_str, f"{fmt} %Y")
                                else:
                                    parsed_date = datetime.strptime(date_str, fmt)
                                break
                            except:
                                pass
                                
                        if not parsed_date:
                            parsed_date = datetime.utcnow()
                            
                        extracted.append({
                            "date": parsed_date,
                            "original_description": raw_desc,
                            "cleaned_description": clean_description(raw_desc),
                            "debit": debit_val,
                            "credit": credit_val,
                            "amount": amount_val,
                            "balance": bal_val,
                            "ref_number": None
                        })
                        
            # If table extraction fails, fall back to regex line by line
            if not extracted:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if date_regex.search(line):
                        # Extract matches
                        date_match = date_regex.search(line).group(0)
                        # Remove date from line to isolate desc & prices
                        remainder = line.replace(date_match, "").strip()
                        
                        # Find numeric amounts
                        num_matches = re.findall(r'\-?\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})\b', remainder)
                        amounts = []
                        for nm in num_matches:
                            val_str = re.sub(r'[^\d\.\-]', '', nm)
                            try:
                                amounts.append(float(val_str))
                            except:
                                pass
                                
                        # Extract description from remaining non-numbers
                        remainder_clean = remainder
                        for nm in num_matches:
                            remainder_clean = remainder_clean.replace(nm, "")
                            
                        raw_desc = " ".join(remainder_clean.split())
                        if not raw_desc:
                            raw_desc = "CRA TRANSACTION"
                            
                        debit_val = 0.0
                        credit_val = 0.0
                        amount_val = 0.0
                        bal_val = 0.0
                        
                        if len(amounts) >= 1:
                            amount_val = amounts[0]
                            if amount_val < 0:
                                debit_val = abs(amount_val)
                            else:
                                credit_val = amount_val
                        if len(amounts) >= 2:
                            bal_val = amounts[-1]
                            
                        parsed_date = None
                        for fmt in ("%b %d", "%b %d, %Y", "%d %b", "%Y-%m-%d", "%d/%m/%Y"):
                            try:
                                date_str = date_match
                                if len(date_match.split()) == 2 and not any(char.isdigit() and len(word) == 4 for word in date_match.split() for char in word):
                                    date_str = f"{date_match} {datetime.utcnow().year}"
                                    parsed_date = datetime.strptime(date_str, f"{fmt} %Y")
                                else:
                                    parsed_date = datetime.strptime(date_str, fmt)
                                break
                            except:
                                pass
                                
                        if not parsed_date:
                            parsed_date = datetime.utcnow()
                            
                        extracted.append({
                            "date": parsed_date,
                            "original_description": raw_desc,
                            "cleaned_description": clean_description(raw_desc),
                            "debit": debit_val,
                            "credit": credit_val,
                            "amount": amount_val,
                            "balance": bal_val,
                            "ref_number": None
                        })
                        
    return extracted
