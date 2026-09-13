import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.models import Client, Transaction
from services.local_mapping_service import (
    LocalMappingEngine, apply_to_suspense_transactions, learn_mapping,
    normalize_vendor,
)
from services.rule_service import create_category_rule


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_client(db, name="Mapper Client"):
    client = Client(business_name=name, fiscal_year_end="Dec 31", status="Active")
    db.add(client)
    db.commit()
    return client


def add_tx(db, client, description, category, review=False):
    tx = Transaction(
        client_id=client.id, account_id=1, date=datetime.datetime.now(),
        original_description=description, cleaned_description=description,
        amount=-25.0, category=category, review_required=review,
    )
    db.add(tx)
    db.commit()
    return tx


def test_normalization_removes_noise_but_keeps_vendor():
    assert normalize_vendor("POS Purchase STARBUCKS #004928") == "STARBUCKS"


def test_priority_learned_mapping_before_rule_and_is_client_scoped():
    db = make_session()
    client = add_client(db)
    other = add_client(db, "Other Client")
    create_category_rule(db, client.id, "STARBUCKS", "Office Supplies")
    learn_mapping(db, client.id, "Starbucks 1234", "Meals & Entertainment")

    result = LocalMappingEngine(db, client.id).categorize("POS STARBUCKS 8899", amount=-8)
    other_result = LocalMappingEngine(db, other.id).categorize("POS STARBUCKS 8899", amount=-8)

    assert result.category == "Meals & Entertainment"
    assert result.source == "learned_vendor"
    assert other_result.review_required is True


def test_repeated_vendor_in_one_unflushed_batch_creates_one_mapping():
    db = make_session()
    db.autoflush = False
    client = add_client(db)

    first = learn_mapping(db, client.id, "OVERLIMIT FEE", "Bank Charges", commit=False)
    second = learn_mapping(db, client.id, "OVERLIMIT FEE", "Bank Charges", commit=False)
    third = learn_mapping(db, client.id, "OVERLIMIT FEE", "Bank Charges", commit=False)
    db.commit()

    from core.models import LearnedMapping
    mappings = db.query(LearnedMapping).filter(LearnedMapping.client_id == client.id).all()
    assert first is second is third
    assert len(mappings) == 1
    assert mappings[0].confirmation_count == 3


def test_keyword_and_regex_rules_are_offline_and_deterministic():
    db = make_session()
    client = add_client(db)
    create_category_rule(db, client.id, "ROGERS", "Telephone Expense")
    create_category_rule(db, client.id, "regex:^CRA.*PAYMENT", "Income Tax Payable")
    mapper = LocalMappingEngine(db, client.id)

    assert mapper.categorize("ROGERS WIRELESS").category == "Telephone Expense"
    assert mapper.categorize("CRA 2026 PAYMENT").source == "regex_rule"


def test_history_and_similarity_with_uncertain_review_queue():
    db = make_session()
    client = add_client(db)
    add_tx(db, client, "ADOBE CREATIVE CLOUD", "Software Subscriptions")
    exact = LocalMappingEngine(db, client.id).categorize("ADOBE CREATIVE CLOUD")
    similar = LocalMappingEngine(db, client.id).categorize("ADOBE CREATIVE CLOUD CANADA")

    assert exact.category == "Software Subscriptions"
    assert exact.review_required is False
    assert similar.category == "Software Subscriptions"
    assert similar.source == "local_similarity"


def test_bulk_apply_never_overwrites_manual_category():
    db = make_session()
    client = add_client(db)
    create_category_rule(db, client.id, "SHELL", "Auto Fuel")
    suspense = add_tx(db, client, "SHELL GAS", "Suspense Expense")
    manual = add_tx(db, client, "SHELL GAS", "Shareholder Loan")

    outcome = apply_to_suspense_transactions(db, client.id)
    db.refresh(suspense)
    db.refresh(manual)

    assert outcome["updated"] == 1
    assert suspense.category == "Auto Fuel"
    assert manual.category == "Shareholder Loan"
