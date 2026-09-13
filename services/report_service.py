from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from core.models import JournalLine, JournalEntry, ClientBankAccount
from services.drilldown_service import (
    get_report_transactions,
    calculate_account_total,
    is_revenue_category,
    cleanup_duplicate_journal_entries
)
import pandas as pd

def compile_trial_balance(
    db: Session,
    client_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> pd.DataFrame:
    """
    Queries journal lines to generate a Trial Balance report.
    Returns DataFrame: Account Name | Debit | Credit
    """
    # Clean any duplicate journal entries before compiling
    cleanup_duplicate_journal_entries(db, client_id)
    
    je_query = db.query(JournalEntry).filter(JournalEntry.client_id == client_id)
    if start_date is not None:
        je_query = je_query.filter(JournalEntry.date >= start_date)
    if end_date is not None:
        je_query = je_query.filter(JournalEntry.date <= end_date)
    entries = je_query.all()
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
        accounts[name]["debit"] += (line.debit or 0.0)
        accounts[name]["credit"] += (line.credit or 0.0)
        
    tb_data = []
    total_debit = 0.0
    total_credit = 0.0
    
    for name, vals in accounts.items():
        net_val = vals["debit"] - vals["credit"]
        if net_val > 0:
            tb_data.append({"Account Name": name, "Debit": round(net_val, 2), "Credit": 0.0})
            total_debit += net_val
        elif net_val < 0:
            tb_data.append({"Account Name": name, "Debit": 0.0, "Credit": round(abs(net_val), 2)})
            total_credit += abs(net_val)
            
    df = pd.DataFrame(tb_data)
    
    # Append total row
    if not df.empty:
        total_row = pd.DataFrame([{
            "Account Name": "TOTAL",
            "Debit": round(total_debit, 2),
            "Credit": round(total_credit, 2)
        }])
        df = pd.concat([df, total_row], ignore_index=True)
        
    return df

def compile_income_statement(
    db: Session,
    client_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Compiles an Income Statement (Profit & Loss) using the unified report transaction engine.
    Ensures 100% reconciliation between the financial statement summary lines and drill-down details.
    """
    # Clean any duplicate journal entries before compiling
    cleanup_duplicate_journal_entries(db, client_id)
    
    items = get_report_transactions(db, client_id, start_date=start_date, end_date=end_date)
    
    # Fetch bank account names to exclude balance sheet accounts
    bank_accs = {a.account_name.strip().lower() for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()}
    bs_exclusions = bank_accs | {
        "gst receivable", "gst payable", "opening balance equity", "due to related party", 
        "due from related party", "shareholder loan", "loan", "retained earnings", 
        "accounts payable", "accounts receivable", "equipment", "accumulated depreciation", 
        "inventory", "capital"
    }
    
    # Group items by category
    by_category: Dict[str, list] = {}
    for item in items:
        cat = (item["category"] or "").strip()
        if not cat:
            cat = "Suspense Revenue" if item["credit"] > item["debit"] else "Suspense Expense"
        if cat.lower() in bs_exclusions:
            continue
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(item)
        
    revenues: Dict[str, float] = {}
    expenses: Dict[str, float] = {}
    total_rev = 0.0
    total_exp = 0.0
    
    for cat, cat_items in by_category.items():
        is_rev = is_revenue_category(cat)
        acc_total = calculate_account_total(cat_items, is_revenue=is_rev)
        
        if is_rev:
            if acc_total != 0.0:
                revenues[cat] = acc_total
                total_rev += acc_total
        else:
            if acc_total != 0.0:
                expenses[cat] = acc_total
                total_exp += acc_total
                
    total_rev = round(total_rev, 2)
    total_exp = round(total_exp, 2)
    net_income = round(total_rev - total_exp, 2)
    
    return {
        "Revenues": revenues,
        "Total Revenue": total_rev,
        "Expenses": expenses,
        "Total Expenses": total_exp,
        "Net Income": net_income,
        "Account_Items": by_category
    }

def compile_balance_sheet(
    db: Session,
    client_id: int,
    as_of_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Compiles a Balance Sheet snapshot.
    Assets = Liabilities + Equity
    """
    # Clean any duplicate journal entries before compiling
    cleanup_duplicate_journal_entries(db, client_id)
    
    je_query = db.query(JournalEntry).filter(JournalEntry.client_id == client_id)
    if as_of_date is not None:
        je_query = je_query.filter(JournalEntry.date <= as_of_date)
    entries = je_query.all()
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
        accounts[name] += ((line.debit or 0.0) - (line.credit or 0.0))
        
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
            bal = round(val + bank_accs.get(name_lower, 0.0), 2)
            assets[name] = bal
            total_assets += bal
            
        # 2. Liabilities (GST Payable, Shareholder Loans, Related Party Loans)
        elif name_lower == "gst payable" or "loan" in name_lower or "related party" in name_lower:
            liab_val = round(abs(val), 2) # Liabilities are credit normal
            liabilities[name] = liab_val
            total_liab += liab_val
            
    # Calculate Net Income from P&L to add to Equity (Retained Earnings)
    pl = compile_income_statement(db, client_id, end_date=as_of_date)
    net_income = pl["Net Income"]
    
    # In double-entry accounting, asset opening balances require a matching Equity credit
    opening_bal_equity = sum(a.opening_balance for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all())
    
    # Check if user manually posted an 'Opening Balance Equity' transaction in the ledger
    ledger_opening = 0.0
    for name, val in accounts.items():
        if name.lower() == "opening balance equity":
            ledger_opening = abs(val)
            
    if ledger_opening > 0:
        opening_bal_equity = ledger_opening
        
    equity["Opening Balance Equity"] = round(opening_bal_equity, 2)
    equity["Retained Earnings"] = round(net_income, 2)
    total_equity += (opening_bal_equity + net_income)
    
    return {
        "Assets": assets,
        "Total Assets": round(total_assets, 2),
        "Liabilities": liabilities,
        "Total Liabilities": round(total_liab, 2),
        "Equity": equity,
        "Total Equity": round(total_equity, 2)
    }
