from sqlalchemy.orm import Session
from core.models import Transaction
from datetime import datetime

def check_is_duplicate(db: Session, client_id: int, account_id: int, tx_date: datetime, amount: float, cleaned_desc: str) -> bool:
    """
    Checks if an identical transaction already exists in the database for this account on the same day.
    """
    # Query matching accounts, amounts, and cleaned merchant names
    matches = db.query(Transaction).filter(
        Transaction.client_id == client_id,
        Transaction.account_id == account_id,
        Transaction.amount == amount,
        Transaction.cleaned_description == cleaned_desc
    ).all()
    
    # Filter for exact date matches (day level precision)
    for m in matches:
        if m.date.date() == tx_date.date():
            return True
            
    return False
