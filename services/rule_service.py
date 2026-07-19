from sqlalchemy.orm import Session
from core.models import CategoryRule, Transaction

def create_category_rule(db: Session, client_id: int, keyword: str, category: str, 
                         gst_treatment: str = "Standard", itc_eligible: bool = True, 
                         business_pct: float = 100.0) -> CategoryRule:
    """
    Creates a new keyword mapping rule for a client.
    """
    kw_clean = keyword.upper().strip()
    existing = db.query(CategoryRule).filter(
        CategoryRule.client_id == client_id,
        CategoryRule.keyword == kw_clean
    ).first()
    
    if existing:
        existing.category = category
        existing.gst_treatment = gst_treatment
        existing.itc_eligible = itc_eligible
        existing.business_pct = business_pct
        db.commit()
        return existing
        
    rule = CategoryRule(
        client_id=client_id,
        keyword=kw_clean,
        category=category,
        gst_treatment=gst_treatment,
        itc_eligible=itc_eligible,
        business_pct=business_pct,
        confidence=1.0 # 1.0 represents a hard local rule
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule

def get_client_rules(db: Session, client_id: int) -> list:
    """
    Returns all category rules configured for a client.
    """
    return db.query(CategoryRule).filter(CategoryRule.client_id == client_id).all()

def match_local_rules(db: Session, client_id: int, merchant_name: str, original_description: str = None) -> CategoryRule:
    """
    Checks if a merchant name or original description matches any local keyword mapping rules.
    Returns the matching rule, or None.
    """
    if not merchant_name:
        return None
        
    rules = get_client_rules(db, client_id)
    merchant_upper = merchant_name.upper()
    orig_upper = original_description.upper() if original_description else merchant_upper
    
    for r in rules:
        if r.keyword in merchant_upper or r.keyword in orig_upper:
            return r
            
    return None
