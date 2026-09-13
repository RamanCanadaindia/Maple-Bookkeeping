from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from core.models import Transaction, JournalEntry, JournalLine, ClientBankAccount, Client, CustomCategory
from services.ai_service import VALID_CATEGORIES

def is_revenue_category(category_name: str) -> bool:
    """
    Determines if an account/category belongs to Operating Revenue based on standard Canadian accounting naming conventions.
    """
    name_lower = (category_name or "").strip().lower()
    if "expense" in name_lower or "cost" in name_lower or "charge" in name_lower:
        return False
    if any(ex in name_lower for ex in [
        "bank fee", "professional fee", "accounting fee", "legal fee", 
        "license fee", "filing fee", "interest expense", "merchant fee"
    ]):
        return False
    revenue_keywords = ["revenue", "sales", "income", "fees earned", "commission", "turnover", "bounty"]
    return any(kw in name_lower for kw in revenue_keywords)

def cleanup_duplicate_journal_entries(db: Session, client_id: Optional[int] = None) -> int:
    """
    Finds and cleans any duplicate JournalEntry records created for the same transaction ID,
    ensuring double-entry records match posted ledger transactions 1-to-1.
    """
    from sqlalchemy import func
    
    subq = db.query(JournalEntry.transaction_id).filter(JournalEntry.transaction_id.isnot(None))
    if client_id is not None:
        subq = subq.filter(JournalEntry.client_id == client_id)
    dup_tx_ids = [r[0] for r in subq.group_by(JournalEntry.transaction_id).having(func.count(JournalEntry.id) > 1).all()]
    
    cleaned_count = 0
    if not dup_tx_ids:
        return 0
        
    for tx_id in dup_tx_ids:
        jes = db.query(JournalEntry).filter(JournalEntry.transaction_id == tx_id).order_by(JournalEntry.id.desc()).all()
        if len(jes) > 1:
            for old_je in jes[1:]:
                db.delete(old_je)
                cleaned_count += 1
    db.commit()
    return cleaned_count

def get_report_transactions(
    db: Session,
    client_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetches the single unified dataset of posted transactions and manual journal entries
    for a client and optional period/category.
    """
    # 1. Fetch bank account mapping for source identification
    bank_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
    bank_map = {b.id: b for b in bank_accounts}
    
    # 2. Query posted transactions
    tx_query = db.query(Transaction).filter(Transaction.client_id == client_id)
    if start_date is not None:
        tx_query = tx_query.filter(Transaction.date >= start_date)
    if end_date is not None:
        tx_query = tx_query.filter(Transaction.date <= end_date)
    if category is not None:
        tx_query = tx_query.filter(Transaction.category == category)
        
    txs = tx_query.order_by(Transaction.date.asc(), Transaction.id.asc()).all()
    
    items: List[Dict[str, Any]] = []
    for tx in txs:
        cat_name = tx.category or ("Suspense Revenue" if tx.amount > 0 else "Suspense Expense")
        amt = tx.amount or 0.0
        debit_val = abs(amt) if amt < 0 else 0.0
        credit_val = amt if amt > 0 else 0.0
        
        bank_obj = bank_map.get(tx.account_id)
        bank_name = bank_obj.account_name if bank_obj else "Bank Account"
        acc_type = (bank_obj.account_type if bank_obj else "Bank").title()
        source_label = f"{acc_type} Transaction"
        
        items.append({
            "id": tx.id,
            "tx_id": tx.id,
            "date": tx.date,
            "vendor": tx.cleaned_description or tx.original_description or "Unknown Vendor",
            "description": tx.original_description or tx.cleaned_description or "",
            "category": cat_name,
            "debit": round(debit_val, 2),
            "credit": round(credit_val, 2),
            "net_amount": round(amt, 2),
            "gst_amount": round(tx.gst_amount or 0.0, 2),
            "itc_amount": round(tx.itc_amount or 0.0, 2),
            "source": source_label,
            "reference": tx.ref_number or f"TX-{tx.id}",
            "bank_account": bank_name,
            "confidence": tx.confidence if tx.confidence is not None else 1.0,
            "review_required": bool(tx.review_required),
            "is_manual": False
        })
        
    # 3. Include manual / unlinked Journal Entries (adjustments without transaction_id)
    je_query = db.query(JournalEntry).filter(JournalEntry.client_id == client_id, JournalEntry.transaction_id == None)
    if start_date is not None:
        je_query = je_query.filter(JournalEntry.date >= start_date)
    if end_date is not None:
        je_query = je_query.filter(JournalEntry.date <= end_date)
    manual_jes = je_query.order_by(JournalEntry.date.asc(), JournalEntry.id.asc()).all()
    
    for je in manual_jes:
        for jl in je.lines:
            if category is not None and jl.account_name != category:
                continue
            is_rev = is_revenue_category(jl.account_name)
            net_amt = (jl.credit - jl.debit) if is_rev else (jl.debit - jl.credit)
            items.append({
                "id": f"JE-{je.id}-{jl.id}",
                "tx_id": None,
                "date": je.date,
                "vendor": je.description or "Manual Journal Entry",
                "description": f"GL Adjustment: {je.description}",
                "category": jl.account_name,
                "debit": round(jl.debit or 0.0, 2),
                "credit": round(jl.credit or 0.0, 2),
                "net_amount": round(net_amt, 2),
                "gst_amount": 0.0,
                "itc_amount": 0.0,
                "source": "Manual Journal Entry",
                "reference": f"JE-{je.id}",
                "bank_account": "General Ledger",
                "confidence": 1.0,
                "review_required": False,
                "is_manual": True
            })
            
    # Sort unified items chronologically
    items.sort(key=lambda x: x["date"] if isinstance(x["date"], datetime) else datetime.min)
    return items

def calculate_account_total(items: List[Dict[str, Any]], is_revenue: bool = False) -> float:
    """
    Calculates net account total consistently:
    - Expense: Debits (withdrawals) - Credits (refunds/deposits)
    - Revenue: Credits (deposits/sales) - Debits (refunds/chargebacks)
    """
    if is_revenue:
        total = sum(item["credit"] - item["debit"] for item in items)
    else:
        total = sum(item["debit"] - item["credit"] for item in items)
    return round(total, 2)

def get_account_drilldown(
    db: Session,
    client_id: int,
    category: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Returns complete drill-down details and reconciled totals for an account line item.
    """
    items = get_report_transactions(db, client_id, start_date=start_date, end_date=end_date, category=category)
    is_rev = is_revenue_category(category)
    account_total = calculate_account_total(items, is_revenue=is_rev)
    
    total_debit = round(sum(i["debit"] for i in items), 2)
    total_credit = round(sum(i["credit"] for i in items), 2)
    total_gst = round(sum(i["gst_amount"] for i in items), 2)
    total_itc = round(sum(i["itc_amount"] for i in items), 2)
    
    return {
        "category": category,
        "is_revenue": is_rev,
        "items": items,
        "count": len(items),
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_gst": total_gst,
        "total_itc": total_itc,
        "drilldown_total": account_total
    }

def reconcile_account(statement_total: float, drilldown_total: float, tolerance: float = 0.01) -> Dict[str, Any]:
    """
    Compares the financial statement line amount with the underlying drill-down total.
    """
    diff = round(abs(statement_total - drilldown_total), 2)
    is_reconciled = diff <= tolerance
    return {
        "statement_total": round(statement_total, 2),
        "drilldown_total": round(drilldown_total, 2),
        "difference": diff,
        "is_reconciled": is_reconciled,
        "status": "Reconciled" if is_reconciled else "Does not reconcile"
    }
