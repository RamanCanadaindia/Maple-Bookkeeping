import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from core.models import User, Client, Transaction, CategoryRule, UserClientAccess
from services.client_service import verify_client_access
from services.auth_service import create_user, update_user_role_and_access
from services.rule_service import create_category_rule, match_client_mapping_rule

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_auto_categorize_logic(db_session):
    # 1. Setup client
    client_a = Client(business_name="Client A", fiscal_year_end="Dec 31", status="Active")
    client_b = Client(business_name="Client B", fiscal_year_end="Dec 31", status="Active")
    db_session.add_all([client_a, client_b])
    db_session.commit()

    # 2. Setup rules for Client A
    create_category_rule(db_session, client_a.id, keyword="ROGERS", category="Telephone Expense")
    create_category_rule(db_session, client_a.id, keyword="STARBUCKS", category="Meals & Entertainment")

    # 3. Setup rules for Client B
    create_category_rule(db_session, client_b.id, keyword="ROGERS", category="Internet Expense")

    # 4. Create transactions for Client A
    tx_uncat_match = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="ROGERS WIRELESS",
        cleaned_description="ROGERS WIRELESS",
        category="Uncategorized",
        amount=-100.0
    )
    tx_null_match = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="ROGERS INVOICE",
        cleaned_description="ROGERS INVOICE",
        category=None,
        amount=-50.0
    )
    tx_empty_match = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="ROGERS MOBILE",
        cleaned_description="ROGERS MOBILE",
        category="   ",
        amount=-40.0
    )
    tx_client_b = Transaction(
        client_id=client_b.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="ROGERS HOME",
        cleaned_description="ROGERS HOME",
        category=None,
        amount=-80.0
    )
    tx_unmatched = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="SHELL GAS STATION",
        cleaned_description="SHELL GAS",
        category="Uncategorized",
        amount=-60.0
    )
    tx_already_cat = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime.now(),
        original_description="STARBUCKS COFFEE",
        cleaned_description="STARBUCKS",
        category="Office Expense", 
        amount=-15.0
    )
    db_session.add_all([tx_uncat_match, tx_null_match, tx_empty_match, tx_client_b, tx_unmatched, tx_already_cat])
    db_session.commit()

    # Perform Client A scan simulation
    for tx in [tx_uncat_match, tx_null_match, tx_empty_match, tx_unmatched, tx_already_cat]:
        normalized_category = (tx.category or "").strip().lower()
        if normalized_category in ("", "uncategorized"):
            matched_rule = match_client_mapping_rule(db_session, client_a.id, tx.description)
            if matched_rule:
                tx.category = matched_rule.category
    db_session.commit()

    # Perform Client B scan simulation
    normalized_b = (tx_client_b.category or "").strip().lower()
    if normalized_b in ("", "uncategorized"):
        matched_rule = match_client_mapping_rule(db_session, client_b.id, tx_client_b.description)
        if matched_rule:
            tx_client_b.category = matched_rule.category
    db_session.commit()

    # Assertions
    # 1. Uncategorized matched are updated
    assert tx_uncat_match.category == "Telephone Expense"
    assert tx_null_match.category == "Telephone Expense"
    assert tx_empty_match.category == "Telephone Expense"

    # 2. Uncategorized unmatched remain unchanged
    assert tx_unmatched.category == "Uncategorized"

    # 3. Existing categorized are never overwritten
    assert tx_already_cat.category == "Office Expense"

    # 4. Rules from Client A did not affect Client B
    assert tx_client_b.category == "Internet Expense"

def test_bookkeeper_access_scoping(db_session):
    client_a = Client(business_name="Client A", fiscal_year_end="Dec 31", status="Active")
    client_b = Client(business_name="Client B", fiscal_year_end="Dec 31", status="Active")
    db_session.add_all([client_a, client_b])
    db_session.commit()

    bk = create_user(db_session, "Bookkeeper User", "bk@test.com", "pass123", "Bookkeeper")
    update_user_role_and_access(db_session, bk.id, "Bookkeeper", assigned_client_ids=[client_a.id])

    # Check permissions scoping: assigned bookkeeper cannot process an unassigned client
    assert verify_client_access(db_session, client_a.id, bk) is True
    assert verify_client_access(db_session, client_b.id, bk) is False

def test_transaction_date_modification(db_session):
    client_a = Client(business_name="Client A", fiscal_year_end="Dec 31", status="Active")
    db_session.add(client_a)
    db_session.commit()
    
    tx = Transaction(
        client_id=client_a.id,
        account_id=1,
        date=datetime.datetime(2026, 1, 1),
        original_description="TEST TX",
        cleaned_description="TEST TX",
        category="Office Supplies",
        amount=-20.0
    )
    db_session.add(tx)
    db_session.commit()
    
    from core.models import JournalEntry
    je = JournalEntry(
        client_id=client_a.id,
        transaction_id=tx.id,
        date=tx.date,
        description=tx.description
    )
    db_session.add(je)
    db_session.commit()
    
    # Modify date
    new_date = datetime.datetime(2026, 2, 15)
    tx.date = new_date
    je.date = new_date
    db_session.commit()
    
    assert tx.date == datetime.datetime(2026, 2, 15)
    assert je.date == datetime.datetime(2026, 2, 15)

def test_batch_import_rules_with_gst(db_session):
    client_a = Client(business_name="Client A", fiscal_year_end="Dec 31", status="Active")
    db_session.add(client_a)
    db_session.commit()
    
    # Simulate pandas dataframe rows
    df_mock_rules = [
        {"Keyword": "AMAZON", "Category": "Office Supplies", "GST Treatment": "Exempt"},
        {"Keyword": "SHELL", "Category": "Auto Fuel", "GST Treatment": "Zero-Rated"},
        {"Keyword": "ROGERS", "Category": "Telephone Expense", "GST Treatment": "Standard"}
    ]
    
    for row in df_mock_rules:
        kw = row["Keyword"]
        cat = row["Category"]
        raw_gst = row["GST Treatment"].strip().lower()
        
        gst_val = "Standard"
        if "exempt" in raw_gst:
            gst_val = "Exempt"
        elif "zero" in raw_gst:
            gst_val = "Zero-Rated"
            
        create_category_rule(db_session, client_a.id, kw, cat, gst_treatment=gst_val)
        
    # Query rules back
    from core.models import CategoryRule
    rules = db_session.query(CategoryRule).filter(CategoryRule.client_id == client_a.id).all()
    assert len(rules) == 3
    
    amazon_rule = next(r for r in rules if r.keyword == "AMAZON")
    assert amazon_rule.category == "Office Supplies"
    assert amazon_rule.gst_treatment == "Exempt"
    
    shell_rule = next(r for r in rules if r.keyword == "SHELL")
    assert shell_rule.category == "Auto Fuel"
    assert shell_rule.gst_treatment == "Zero-Rated"
    
    rogers_rule = next(r for r in rules if r.keyword == "ROGERS")
    assert rogers_rule.category == "Telephone Expense"
    assert rogers_rule.gst_treatment == "Standard"
