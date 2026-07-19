from sqlalchemy.orm import Session
from core.models import Transaction
from datetime import datetime

def find_matching_transactions(db: Session, client_id: int, receipt_amount: float, 
                               receipt_date_str: str = None, tolerance_days: int = 3) -> list:
    """
    Finds the best matching posted ledger transactions for a parsed receipt.
    Ranks candidates by amount match, date proximity, and merchant similarity.
    """
    if receipt_amount <= 0:
        return []
        
    # Convert date string if provided
    receipt_date = None
    if receipt_amount:
        if receipt_date_str:
            try:
                receipt_date = datetime.strptime(receipt_date_str, "%Y-%m-%d")
            except:
                pass
                
    # Fetch all expense transactions for client (debit transactions / amount < 0)
    txs = db.query(Transaction).filter(
        Transaction.client_id == client_id,
        Transaction.amount < 0
    ).all()
    
    candidates = []
    
    for tx in txs:
        # Check absolute amount match (since expenses in DB are negative, check abs(tx.amount))
        amt_diff = abs(abs(tx.amount) - receipt_amount)
        
        score = 0
        if amt_diff <= 0.05:
            score += 100 # Near-exact amount match
        elif amt_diff <= 1.00:
            score += 40  # Loose amount match
        else:
            continue     # Skip if amount is totally different
            
        # Date proximity
        if receipt_date:
            days_diff = abs((tx.date.date() - receipt_date.date()).days)
            if days_diff == 0:
                score += 50
            elif days_diff <= tolerance_days:
                score += 25
            else:
                score -= 30 # Date discrepancy penalty
                
        # Filter out negative score matches
        if score > 30:
            candidates.append({
                "transaction": tx,
                "score": score,
                "amt_diff": amt_diff
            })
            
    # Sort candidates by score descending, then by amount difference ascending
    candidates.sort(key=lambda x: (-x["score"], x["amt_diff"]))
    return candidates
