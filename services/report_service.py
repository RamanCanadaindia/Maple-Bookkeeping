from sqlalchemy.orm import Session
from core.models import JournalLine, JournalEntry, ClientBankAccount
import pandas as pd

def compile_trial_balance(db: Session, client_id: int) -> pd.DataFrame:
    """
    Queries journal lines to generate a Trial Balance report.
    Returns DataFrame: Account Name | Debit | Credit
    """
    entries = db.query(JournalEntry).filter(JournalEntry.client_id == client_id).all()
    entry_ids = [e.id for e in entries]
    
    if not entry_ids:
        return pd.DataFrame(columns=["Account Name", "Debit", "Credit"])
        
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id.in_(entry_ids)).all()
    
    # Aggregate by account
    accounts = {}
    for line in lines:
        name = line.account_name
        if name not in accounts:
            accounts[name] = {"debit": 0.0, "credit": 0.0}
        accounts[name]["debit"] += line.debit
        accounts[name]["credit"] += line.credit
        
    tb_data = []
    total_debit = 0.0
    total_credit = 0.0
    
    for name, vals in accounts.items():
        net_val = vals["debit"] - vals["credit"]
        if net_val > 0:
            tb_data.append({"Account Name": name, "Debit": net_val, "Credit": 0.0})
            total_debit += net_val
        elif net_val < 0:
            tb_data.append({"Account Name": name, "Debit": 0.0, "Credit": abs(net_val)})
            total_credit += abs(net_val)
            
    df = pd.DataFrame(tb_data)
    
    # Append total row
    if not df.empty:
        total_row = pd.DataFrame([{"Account Name": "TOTAL", "Debit": total_debit, "Credit": total_credit}])
        df = pd.concat([df, total_row], ignore_index=True)
        
    return df

def compile_income_statement(db: Session, client_id: int) -> dict:
    """
    Compiles an Income Statement (Profit & Loss).
    Categorizes revenue and expenses net of GST.
    """
    entries = db.query(JournalEntry).filter(JournalEntry.client_id == client_id).all()
    entry_ids = [e.id for e in entries]
    
    if not entry_ids:
        return {
            "Revenues": {}, "Total Revenue": 0.0,
            "Expenses": {}, "Total Expenses": 0.0,
            "Net Income": 0.0
        }
        
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id.in_(entry_ids)).all()
    
    # Aggregate net movements
    accounts = {}
    for line in lines:
        name = line.account_name
        if name not in accounts:
            accounts[name] = 0.0
        # Normal debit/credit rules
        accounts[name] += (line.debit - line.credit)
        
    revenues = {}
    expenses = {}
    total_rev = 0.0
    total_exp = 0.0
    
    # Classify based on standard accounts
    # Bank accounts are excluded from P&L (they go to Balance Sheet)
    bank_accs = {a.account_name.lower() for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()}
    
    for name, val in accounts.items():
        name_lower = name.lower()
        if name_lower in bank_accs or name_lower in ["gst receivable", "gst payable"]:
            continue
            
        # If it's a credit balance in revenue or sales
        if ("revenue" in name_lower or "sales" in name_lower or "fees" in name_lower) and "bank fees" not in name_lower:
            rev_val = abs(val) # Revenue is credit normal
            revenues[name] = rev_val
            total_rev += rev_val
        else:
            # Expense is debit normal
            exp_val = val # positive means net debit
            if exp_val != 0.0:
                expenses[name] = exp_val
                total_exp += exp_val
                
    return {
        "Revenues": revenues,
        "Total Revenue": round(total_rev, 2),
        "Expenses": expenses,
        "Total Expenses": round(total_exp, 2),
        "Net Income": round(total_rev - total_exp, 2)
    }

def compile_balance_sheet(db: Session, client_id: int) -> dict:
    """
    Compiles a Balance Sheet snapshot.
    Assets = Liabilities + Equity
    """
    entries = db.query(JournalEntry).filter(JournalEntry.client_id == client_id).all()
    entry_ids = [e.id for e in entries]
    
    if not entry_ids:
        return {
            "Assets": {}, "Total Assets": 0.0,
            "Liabilities": {}, "Total Liabilities": 0.0,
            "Equity": {}, "Total Equity": 0.0
        }
        
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id.in_(entry_ids)).all()
    
    accounts = {}
    for line in lines:
        name = line.account_name
        if name not in accounts:
            accounts[name] = 0.0
        accounts[name] += (line.debit - line.credit)
        
    assets = {}
    liabilities = {}
    equity = {}
    
    total_assets = 0.0
    total_liab = 0.0
    total_equity = 0.0
    
    # Link account list to identify bank assets
    bank_accs = {a.account_name.lower(): a.opening_balance for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()}
    
    for name, val in accounts.items():
        name_lower = name.lower()
        
        # 1. Assets (Bank Accounts, GST Receivable)
        if name_lower in bank_accs or name_lower == "gst receivable":
            # Add opening balance to bank assets
            bal = val + bank_accs.get(name_lower, 0.0)
            assets[name] = bal
            total_assets += bal
            
        # 2. Liabilities (GST Payable, Shareholder Loans, Related Party Loans)
        elif name_lower == "gst payable" or "loan" in name_lower or "related party" in name_lower:
            liab_val = abs(val) # Liabilities are credit normal
            liabilities[name] = liab_val
            total_liab += liab_val
            
    # Calculate Net Income from P&L to add to Equity (Retained Earnings)
    pl = compile_income_statement(db, client_id)
    net_income = pl["Net Income"]
    
    # In double-entry accounting, asset opening balances require a matching Equity credit
    opening_bal_equity = sum(a.opening_balance for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all())
    
    # Check if user manually posted an 'Opening Balance Equity' transaction in the ledger
    ledger_opening = 0.0
    for name, val in accounts.items():
        if name.lower() == "opening balance equity":
            ledger_opening = abs(val) # credit balance is negative in accounts, so take absolute value
            
    if ledger_opening > 0:
        opening_bal_equity = ledger_opening
        
    equity["Opening Balance Equity"] = opening_bal_equity
    equity["Retained Earnings"] = net_income
    total_equity += (opening_bal_equity + net_income)
    
    return {
        "Assets": assets,
        "Total Assets": round(total_assets, 2),
        "Liabilities": liabilities,
        "Total Liabilities": round(total_liab, 2),
        "Equity": equity,
        "Total Equity": round(total_equity, 2)
    }
