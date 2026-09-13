from sqlalchemy.orm import Session
from core.models import Transaction, Client

from sqlalchemy.orm import Session

def calculate_transaction_gst(tx: Transaction, client: Client, db: Session = None) -> tuple:
    """
    Computes GST rate, GST amount, and Input Tax Credit (ITC) eligibility for a transaction.
    Only calculates GST if an explicit user-defined CategoryRule matches.
    Does NOT automatically force or guess GST on transactions without explicit user instructions/rules.
    Returns (gst_amount, itc_eligible_amount).
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
                
            cat_lower = (rule.category or "").lower()
            if "vehicle" in cat_lower or "fuel" in cat_lower or "gas" in cat_lower or "auto" in cat_lower:
                factor = ((rule.business_pct or 100.0) / 100.0) * ((client.business_use_pct or 100.0) / 100.0)
            else:
                factor = (rule.business_pct or 100.0) / 100.0
                
            itc_eligible_amount = round(gst_amount * factor, 2)
            
            if "meals" in cat_lower or "entertainment" in cat_lower or "food" in cat_lower:
                itc_eligible_amount = round(itc_eligible_amount * 0.50, 2)
                
            return gst_amount, itc_eligible_amount

    # 2. No automatic guessing: Default to 0.0 / 0.0 until user manually sets GST or defines a rule
    return 0.0, 0.0

def generate_gst_return_summary(db: Session, client_id: int, start_date=None, end_date=None) -> dict:
    """
    Generates a Netfile-ready GST return summary with complete transaction breakdown.
    Supports Regular Method and Quick Method, date range filtering, and category-level ITC tracking.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {}
        
    query = db.query(Transaction).filter(Transaction.client_id == client_id)
    if start_date is not None:
        query = query.filter(Transaction.date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.date <= end_date)
    txs = query.order_by(Transaction.date.asc()).all()
    
    gst_collected = 0.0
    gst_paid = 0.0
    itc_claimed = 0.0
    gross_sales = 0.0
    
    sales_items = []
    itc_by_category = {}
    treatment_stats = {
        "Standard (5%)": {"spend": 0.0, "gst_paid": 0.0, "itc_claimed": 0.0, "count": 0},
        "Meals (50% ITC)": {"spend": 0.0, "gst_paid": 0.0, "itc_claimed": 0.0, "count": 0},
        "Vehicle / Business %": {"spend": 0.0, "gst_paid": 0.0, "itc_claimed": 0.0, "count": 0},
        "Exempt / Zero-Rated": {"spend": 0.0, "gst_paid": 0.0, "itc_claimed": 0.0, "count": 0}
    }
    
    for tx in txs:
        gst_amt = round(tx.gst_amount or 0.0, 2)
        itc_eligible = round(tx.itc_amount or 0.0, 2)
        cat_name = tx.category or "Uncategorized"
        category_lower = cat_name.lower()
        
        is_revenue = (
            ("revenue" in category_lower or "sales" in category_lower or "fees" in category_lower or "income" in category_lower)
            and "bank fees" not in category_lower
        )

        amount_val = abs(tx.amount)
        dt_val = tx.date
        vendor_val = tx.cleaned_description or tx.original_description or "Unknown Vendor"
        memo_val = tx.original_description or ""

        if is_revenue:
            if tx.amount > 0:
                net_sale = amount_val - gst_amt
                gross_sales += net_sale
                gst_collected += gst_amt
                sales_items.append({
                    "tx_id": tx.id,
                    "date": dt_val,
                    "vendor": vendor_val,
                    "description": memo_val,
                    "category": cat_name,
                    "total_amount": amount_val,
                    "net_sales": net_sale,
                    "gst_collected": gst_amt,
                    "type": "Sale"
                })
            else:
                # Customer refund/credit note
                net_sale = -(amount_val - gst_amt)
                gross_sales += net_sale
                gst_collected -= gst_amt
                sales_items.append({
                    "tx_id": tx.id,
                    "date": dt_val,
                    "vendor": vendor_val,
                    "description": memo_val,
                    "category": cat_name,
                    "total_amount": -amount_val,
                    "net_sales": net_sale,
                    "gst_collected": -gst_amt,
                    "type": "Customer Refund"
                })
        else:
            # Expense item
            if tx.amount < 0:
                tx_spend = amount_val
                tx_gst = gst_amt
                
                # Determine actual ITC claim based on method
                if client.gst_method == "Regular":
                    actual_itc = itc_eligible
                else:
                    actual_itc = itc_eligible if ("capital" in category_lower or "equipment" in category_lower) else 0.0
                    
                gst_paid += tx_gst
                itc_claimed += actual_itc
                sign_mult = 1.0
            else:
                # Expense refund/reimbursement
                tx_spend = -amount_val
                tx_gst = -gst_amt
                if client.gst_method == "Regular":
                    actual_itc = -itc_eligible
                else:
                    actual_itc = -itc_eligible if ("capital" in category_lower or "equipment" in category_lower) else 0.0
                    
                gst_paid += tx_gst
                itc_claimed += actual_itc
                sign_mult = -1.0
                
            # Classify tax treatment for reporting breakdown
            if tx_gst == 0.0:
                treatment_key = "Exempt / Zero-Rated"
            elif "meals" in category_lower or "entertainment" in category_lower or "food" in category_lower:
                treatment_key = "Meals (50% ITC)"
            elif "vehicle" in category_lower or "fuel" in category_lower or "gas" in category_lower or "auto" in category_lower:
                treatment_key = "Vehicle / Business %"
            else:
                treatment_key = "Standard (5%)"
                
            treatment_stats[treatment_key]["spend"] += tx_spend
            treatment_stats[treatment_key]["gst_paid"] += tx_gst
            treatment_stats[treatment_key]["itc_claimed"] += actual_itc
            treatment_stats[treatment_key]["count"] += 1
            
            # Group by category
            if cat_name not in itc_by_category:
                itc_by_category[cat_name] = {
                    "category": cat_name,
                    "total_spend": 0.0,
                    "gst_paid": 0.0,
                    "itc_claimed": 0.0,
                    "count": 0,
                    "items": []
                }
            itc_by_category[cat_name]["total_spend"] += tx_spend
            itc_by_category[cat_name]["gst_paid"] += tx_gst
            itc_by_category[cat_name]["itc_claimed"] += actual_itc
            itc_by_category[cat_name]["count"] += 1
            itc_by_category[cat_name]["items"].append({
                "tx_id": tx.id,
                "date": dt_val,
                "vendor": vendor_val,
                "description": memo_val,
                "spend": tx_spend,
                "gst_paid": tx_gst,
                "itc_claimed": actual_itc,
                "treatment": treatment_key
            })
                    
    # Quick method remittance calculation
    if client.gst_method == "Quick Method":
        gst_remittance = round(gross_sales * 0.036, 2)
        net_tax = gst_remittance - itc_claimed
    else:
        net_tax = gst_collected - itc_claimed
        
    return {
        "method": client.gst_method,
        "period": client.gst_period,
        "gross_sales_revenue": round(gross_sales, 2),
        "gst_collected_line103": round(gst_collected, 2),
        "itcs_claimed_line108": round(itc_claimed, 2),
        "net_tax_due_line109": round(net_tax, 2),
        "sales_items": sales_items,
        "itc_by_category": itc_by_category,
        "treatment_stats": treatment_stats
    }
