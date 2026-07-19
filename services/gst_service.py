from sqlalchemy.orm import Session
from core.models import Transaction, Client

from sqlalchemy.orm import Session

def calculate_transaction_gst(tx: Transaction, client: Client, db: Session = None) -> tuple:
    """
    Computes GST rate, GST amount, and Input Tax Credit (ITC) eligibility for a transaction.
    If a DB session is provided, queries matching keyword rules first.
    Applies special Canadian rules:
    - Meals & Entertainment: 50% limit.
    - Mixed Use/Vehicle: multiplied by client.business_use_pct.
    Returns (gst_amount, itc_eligible_amount)
    """
    # 1. Check local keyword rules first if db session is provided
    if db:
        from services.rule_service import match_local_rules
        rule = match_local_rules(db, tx.client_id, tx.cleaned_description, tx.original_description)
        # Only use the rule if the transaction's category is not set, or matches the rule's category
        if rule and (not tx.category or tx.category == rule.category):
            if rule.gst_treatment in ["Exempt", "Zero-Rated"]:
                return 0.0, 0.0
            
            amount = abs(tx.amount)
            gst_rate = 0.05
            gst_amount = round(amount * (gst_rate / (1.0 + gst_rate)), 2)
            
            if not rule.itc_eligible:
                return gst_amount, 0.0
                
            cat_lower = rule.category.lower()
            if "vehicle" in cat_lower or "fuel" in cat_lower or "gas" in cat_lower or "auto" in cat_lower:
                factor = ((rule.business_pct or 100.0) / 100.0) * ((client.business_use_pct or 100.0) / 100.0)
            else:
                factor = (rule.business_pct or 100.0) / 100.0
                
            itc_eligible_amount = round(gst_amount * factor, 2)
            
            if "meals" in cat_lower or "entertainment" in cat_lower or "food" in cat_lower:
                itc_eligible_amount = round(itc_eligible_amount * 0.50, 2)
                
            return gst_amount, itc_eligible_amount

    # 2. Fall back to category-based standard rules
    # 5% GST is standard in Canada
    gst_rate = 0.05
    amount = abs(tx.amount)
    category_lower = (tx.category or "").lower()
    
    # Non-taxable categories (CRA payments, Bank charges, transfers)
    exempt_categories = [
        "transfer", "shareholder", "loan", "interest", "bank charges", 
        "bank fees", "cra", "tax", "payroll", "dividend", 
        "due to related party", "opening balance equity", "equity"
    ]
    if any(ec in category_lower for ec in exempt_categories):
        return 0.0, 0.0
        
    # Calculate GST paid (assuming standard 5% included in total: GST = Total * 5/105)
    gst_amount = round(amount * (gst_rate / (1.0 + gst_rate)), 2)
    itc_eligible_amount = gst_amount
    
    # Meals & Entertainment rule (50% limit)
    if "meals" in category_lower or "entertainment" in category_lower or "food" in category_lower:
        itc_eligible_amount = round(gst_amount * 0.50, 2)
        
    # Vehicle / Mixed-use expenses rule (Business Use %)
    elif "vehicle" in category_lower or "fuel" in category_lower or "gas" in category_lower or "auto" in category_lower:
        factor = (client.business_use_pct or 100.0) / 100.0
        itc_eligible_amount = round(gst_amount * factor, 2)
        
    return gst_amount, itc_eligible_amount

def generate_gst_return_summary(db: Session, client_id: int) -> dict:
    """
    Generates a Netfile-ready GST return summary.
    Supports Regular Method and Quick Method.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {}
        
    txs = db.query(Transaction).filter(Transaction.client_id == client_id).all()
    
    gst_collected = 0.0
    gst_paid = 0.0
    itc_claimed = 0.0
    gross_sales = 0.0
    
    for tx in txs:
        # Use stored database values (respects manual edits, bulk updates, and custom exemptions)
        gst_amt = tx.gst_amount if tx.gst_amount is not None else 0.0
        itc_eligible = tx.itc_amount if tx.itc_amount is not None else 0.0
        
        if tx.amount > 0:
            # Revenue (deposit)
            gross_sales += tx.amount
            gst_collected += gst_amt
        else:
            # Expense (withdrawal)
            gst_paid += gst_amt
            # Only claim ITCs if Regular Method or Capital purchases
            if client.gst_method == "Regular":
                itc_claimed += itc_eligible
            else:
                # Quick Method: Can only claim ITCs on Capital Assets
                if "capital" in (tx.category or "").lower() or "equipment" in (tx.category or "").lower():
                    itc_claimed += itc_eligible
                    
    # Quick method remittance calculation
    # e.g., BC services rate is 3.6% of gross sales (including GST)
    if client.gst_method == "Quick Method":
        # Remittance = Gross Revenue * 3.6%
        gst_remittance = round(gross_sales * 0.036, 2)
        net_tax = gst_remittance - itc_claimed
    else:
        # Regular method
        net_tax = gst_collected - itc_claimed
        
    return {
        "method": client.gst_method,
        "period": client.gst_period,
        "gross_sales_revenue": round(gross_sales, 2),
        "gst_collected_line103": round(gst_collected, 2),
        "itcs_claimed_line108": round(itc_claimed, 2),
        "net_tax_due_line109": round(net_tax, 2)
    }
