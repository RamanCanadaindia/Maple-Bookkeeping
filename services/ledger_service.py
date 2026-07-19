from sqlalchemy.orm import Session
from core.models import Transaction, JournalEntry, JournalLine, ClientBankAccount
from datetime import datetime

def post_transaction_to_gl(db: Session, tx: Transaction) -> JournalEntry:
    """
    Translates a transaction into a balanced double-entry JournalEntry.
    Splits GST tax amounts automatically.
    """
    # 1. Fetch bank account details
    acc = db.query(ClientBankAccount).filter(ClientBankAccount.id == tx.account_id).first()
    bank_acc_name = acc.account_name if acc else "Bank Account"
    
    # Check if a journal entry already exists for this transaction
    existing = db.query(JournalEntry).filter(JournalEntry.transaction_id == tx.id).first()
    if existing:
        # Delete old journal entry lines to overwrite
        db.delete(existing)
        db.commit()
        
    entry = JournalEntry(
        client_id=tx.client_id,
        transaction_id=tx.id,
        date=tx.date,
        description=tx.cleaned_description
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    lines = []
    
    # Calculate amount values
    total_amt = abs(tx.amount)
    
    # 2. Determine journal lines
    if tx.amount < 0:
        # Withdrawal / Expense / Output
        # Credit Bank
        bank_line = JournalLine(
            journal_entry_id=entry.id,
            account_name=bank_acc_name,
            debit=0.0,
            credit=total_amt
        )
        lines.append(bank_line)
        
        # Split GST using claimable Input Tax Credit (ITC)
        itc_amt = getattr(tx, 'itc_amount', 0.0) or 0.0
        expense_amt = total_amt - itc_amt
        
        # Mapped Category (Debit Expense)
        category_name = tx.category or "Suspense Expense"
        exp_line = JournalLine(
            journal_entry_id=entry.id,
            account_name=category_name,
            debit=expense_amt,
            credit=0.0
        )
        lines.append(exp_line)
        
        # GST Input Tax Credit (Debit GST Receivable)
        if itc_amt > 0:
            gst_line = JournalLine(
                journal_entry_id=entry.id,
                account_name="GST Receivable",
                debit=itc_amt,
                credit=0.0
            )
            lines.append(gst_line)
            
    else:
        # Deposit / Revenue / Input
        # Debit Bank
        bank_line = JournalLine(
            journal_entry_id=entry.id,
            account_name=bank_acc_name,
            debit=total_amt,
            credit=0.0
        )
        lines.append(bank_line)
        
        gst_amt = getattr(tx, 'gst_amount', 0.0) or 0.0
        revenue_amt = total_amt - gst_amt
        
        # Mapped Category (Credit Revenue)
        category_name = tx.category or "Suspense Revenue"
        rev_line = JournalLine(
            journal_entry_id=entry.id,
            account_name=category_name,
            debit=0.0,
            credit=revenue_amt
        )
        lines.append(rev_line)
        
        # GST Collected (Credit GST Payable)
        if gst_amt > 0:
            gst_line = JournalLine(
                journal_entry_id=entry.id,
                account_name="GST Payable",
                debit=0.0,
                credit=gst_amt
            )
            lines.append(gst_line)
            
    # Save lines to database
    for line in lines:
        db.add(line)
        
    db.commit()
    return entry

def update_transaction_category(db: Session, tx_id: int, new_category: str) -> Transaction:
    """
    Updates a transaction's category, re-calculates GST sales taxes / claimable ITCs, 
    and regenerates its double-entry journal entry records.
    """
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise ValueError("Transaction not found.")
        
    from core.models import Client
    client = db.query(Client).filter(Client.id == tx.client_id).first()
    
    tx.category = new_category
    
    # Re-calculate GST/ITCs based on the new category guidelines
    from services.gst_service import calculate_transaction_gst
    gst_val, itc_val = calculate_transaction_gst(tx, client, db=db)
    tx.gst_amount = gst_val
    tx.itc_amount = itc_val
    db.add(tx)
    db.commit()
    
    # Re-generate GL double-entry lines
    post_transaction_to_gl(db, tx)
    
    return tx

def update_transaction_gst_manual(db: Session, tx_id: int, new_gst: float, new_itc: float) -> Transaction:
    """
    Manually overrides a transaction's GST and ITC amounts,
    and regenerates its double-entry journal entry records.
    """
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise ValueError("Transaction not found.")
        
    tx.gst_amount = new_gst
    tx.itc_amount = new_itc
    db.add(tx)
    db.commit()
    
    # Re-generate GL double-entry lines
    post_transaction_to_gl(db, tx)
    
    return tx
