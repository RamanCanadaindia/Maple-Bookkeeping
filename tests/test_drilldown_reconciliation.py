import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from core.models import Client, ClientBankAccount, Transaction, JournalEntry, JournalLine, CustomCategory
from services.ledger_service import post_transaction_to_gl
from services.drilldown_service import (
    get_report_transactions,
    get_account_drilldown,
    calculate_account_total,
    reconcile_account,
    cleanup_duplicate_journal_entries
)
from services.report_service import compile_income_statement

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_expense_reconciliation(db_session):
    """
    Test 1: Expense reconciliation
    Transactions:
      - Repair debit $1,000
      - Repair debit $500
      - Repair credit $100
    Expected net balance: $1,400.
    Income Statement total and drill-down total must both equal $1,400.
    """
    client = Client(business_name="Test Transport Ltd", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    
    bank_acc = ClientBankAccount(client_id=client.id, account_name="Checking", account_type="Bank", opening_balance=5000.0)
    db_session.add(bank_acc)
    db_session.commit()
    
    tx1 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 3, 1), original_description="Parts shop", cleaned_description="PARTS SHOP", category="Repairs", amount=-1000.0)
    tx2 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 3, 5), original_description="Kal Tire", cleaned_description="KAL TIRE", category="Repairs", amount=-500.0)
    tx3 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 3, 10), original_description="Parts refund", cleaned_description="PARTS REFUND", category="Repairs", amount=100.0)
    
    db_session.add_all([tx1, tx2, tx3])
    db_session.commit()
    
    for tx in [tx1, tx2, tx3]:
        post_transaction_to_gl(db_session, tx)
        
    pl = compile_income_statement(db_session, client.id)
    statement_repairs = pl["Expenses"].get("Repairs", 0.0)
    
    drilldown = get_account_drilldown(db_session, client.id, "Repairs")
    drilldown_repairs = drilldown["drilldown_total"]
    
    assert statement_repairs == 1400.0
    assert drilldown_repairs == 1400.0
    assert statement_repairs == drilldown_repairs
    
    recon = reconcile_account(statement_repairs, drilldown_repairs)
    assert recon["is_reconciled"] is True
    assert recon["difference"] == 0.0
    assert recon["status"] == "Reconciled"
    assert len(drilldown["items"]) == 3

def test_client_isolation(db_session):
    """
    Test 2: Client isolation
    Transactions for Client A must never appear in Client B drill-down.
    """
    client_a = Client(business_name="Client A Corp", fiscal_year_end="December 31", status="Active")
    client_b = Client(business_name="Client B Corp", fiscal_year_end="December 31", status="Active")
    db_session.add_all([client_a, client_b])
    db_session.commit()
    
    bank_a = ClientBankAccount(client_id=client_a.id, account_name="Bank A", account_type="Bank")
    bank_b = ClientBankAccount(client_id=client_b.id, account_name="Bank B", account_type="Bank")
    db_session.add_all([bank_a, bank_b])
    db_session.commit()
    
    tx_a = Transaction(client_id=client_a.id, account_id=bank_a.id, date=datetime(2026, 2, 1), original_description="A expense", cleaned_description="A EXPENSE", category="Office Expense", amount=-250.0)
    tx_b = Transaction(client_id=client_b.id, account_id=bank_b.id, date=datetime(2026, 2, 1), original_description="B expense", cleaned_description="B EXPENSE", category="Office Expense", amount=-750.0)
    db_session.add_all([tx_a, tx_b])
    db_session.commit()
    
    post_transaction_to_gl(db_session, tx_a)
    post_transaction_to_gl(db_session, tx_b)
    
    drilldown_a = get_account_drilldown(db_session, client_a.id, "Office Expense")
    drilldown_b = get_account_drilldown(db_session, client_b.id, "Office Expense")
    
    assert drilldown_a["drilldown_total"] == 250.0
    assert len(drilldown_a["items"]) == 1
    assert drilldown_a["items"][0]["vendor"] == "A EXPENSE"
    
    assert drilldown_b["drilldown_total"] == 750.0
    assert len(drilldown_b["items"]) == 1
    assert drilldown_b["items"][0]["vendor"] == "B EXPENSE"

def test_date_filtering(db_session):
    """
    Test 3: Date filtering
    Transactions outside the selected fiscal period must not appear.
    """
    client = Client(business_name="Date Test Client", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    bank_acc = ClientBankAccount(client_id=client.id, account_name="Checking", account_type="Bank")
    db_session.add(bank_acc)
    db_session.commit()
    
    # 2025 transaction (prior year)
    tx_2025 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2025, 12, 15), original_description="Old Fuel", cleaned_description="OLD FUEL", category="Vehicle Expense", amount=-300.0)
    # 2026 transaction (current period)
    tx_2026 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 6, 20), original_description="Current Fuel", cleaned_description="CURRENT FUEL", category="Vehicle Expense", amount=-450.0)
    # 2027 transaction (future period)
    tx_2027 = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2027, 1, 10), original_description="Future Fuel", cleaned_description="FUTURE FUEL", category="Vehicle Expense", amount=-600.0)
    db_session.add_all([tx_2025, tx_2026, tx_2027])
    db_session.commit()
    
    for t in [tx_2025, tx_2026, tx_2027]:
        post_transaction_to_gl(db_session, t)
        
    start_dt = datetime(2026, 1, 1)
    end_dt = datetime(2026, 12, 31, 23, 59, 59)
    
    pl_2026 = compile_income_statement(db_session, client.id, start_date=start_dt, end_date=end_dt)
    drilldown_2026 = get_account_drilldown(db_session, client.id, "Vehicle Expense", start_date=start_dt, end_date=end_dt)
    
    assert pl_2026["Expenses"].get("Vehicle Expense") == 450.0
    assert drilldown_2026["drilldown_total"] == 450.0
    assert len(drilldown_2026["items"]) == 1
    assert drilldown_2026["items"][0]["vendor"] == "CURRENT FUEL"

def test_custom_category(db_session):
    """
    Test 4: Custom category
    A newly created custom category must support drill-down and reconciliation.
    """
    client = Client(business_name="Custom Cat Client", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    
    custom_cat = CustomCategory(client_id=client.id, name="Special Equipment Maintenance")
    db_session.add(custom_cat)
    bank_acc = ClientBankAccount(client_id=client.id, account_name="Checking", account_type="Bank")
    db_session.add(bank_acc)
    db_session.commit()
    
    tx = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 5, 1), original_description="Hydraulic pump", cleaned_description="HYDRAULIC PUMP", category="Special Equipment Maintenance", amount=-1875.50)
    db_session.add(tx)
    db_session.commit()
    post_transaction_to_gl(db_session, tx)
    
    pl = compile_income_statement(db_session, client.id)
    drilldown = get_account_drilldown(db_session, client.id, "Special Equipment Maintenance")
    
    assert pl["Expenses"].get("Special Equipment Maintenance") == 1875.50
    assert drilldown["drilldown_total"] == 1875.50
    assert drilldown["items"][0]["vendor"] == "HYDRAULIC PUMP"
    
    recon = reconcile_account(pl["Expenses"]["Special Equipment Maintenance"], drilldown["drilldown_total"])
    assert recon["is_reconciled"] is True

def test_journal_entries_in_drilldown(db_session):
    """
    Test 5: Journal entries
    If manual journal entries affect the Income Statement, they must appear in the drill-down with proper Source.
    """
    client = Client(business_name="JE Client", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    
    # Create a manual adjusting journal entry
    je = JournalEntry(client_id=client.id, transaction_id=None, date=datetime(2026, 4, 15), description="Year-end accounting adjustment")
    db_session.add(je)
    db_session.commit()
    
    line1 = JournalLine(journal_entry_id=je.id, account_name="Professional Fees", debit=1200.0, credit=0.0)
    line2 = JournalLine(journal_entry_id=je.id, account_name="Accounts Payable", debit=0.0, credit=1200.0)
    db_session.add_all([line1, line2])
    db_session.commit()
    
    pl = compile_income_statement(db_session, client.id)
    drilldown = get_account_drilldown(db_session, client.id, "Professional Fees")
    
    assert pl["Expenses"].get("Professional Fees") == 1200.0
    assert drilldown["drilldown_total"] == 1200.0
    assert len(drilldown["items"]) == 1
    assert drilldown["items"][0]["source"] == "Manual Journal Entry"
    assert drilldown["items"][0]["reference"] == f"JE-{je.id}"

def test_reconciliation_math(db_session):
    """
    Test 6: Reconciliation
    For every account tested: statement_total == drilldown_total within rounding tolerance.
    """
    client = Client(business_name="Full Recon Client", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    bank_acc = ClientBankAccount(client_id=client.id, account_name="Operating TD", account_type="Bank")
    db_session.add(bank_acc)
    db_session.commit()
    
    # Add multiple diverse revenue and expense transactions
    tx_list = [
        Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 1, 10), original_description="Client Invoice 101", cleaned_description="INVOICE 101", category="Trade Sales", amount=15000.0),
        Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 1, 15), original_description="Consulting Project", cleaned_description="CONSULTING FEE", category="Consulting Revenue", amount=4500.0),
        Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 1, 20), original_description="Office Depot", cleaned_description="OFFICE DEPOT", category="Office Supplies", amount=-342.80),
        Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 1, 25), original_description="Facebook Ads", cleaned_description="META ADS", category="Advertising", amount=-1250.00),
        Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 1, 28), original_description="Google Ads Refund", cleaned_description="GOOGLE ADS REFUND", category="Advertising", amount=150.00),
    ]
    db_session.add_all(tx_list)
    db_session.commit()
    
    for tx in tx_list:
        post_transaction_to_gl(db_session, tx)
        
    pl = compile_income_statement(db_session, client.id)
    
    # Check all revenue accounts
    for rev_name, rev_amt in pl["Revenues"].items():
        dd = get_account_drilldown(db_session, client.id, rev_name)
        assert dd["drilldown_total"] == rev_amt
        recon = reconcile_account(rev_amt, dd["drilldown_total"])
        assert recon["is_reconciled"] is True
        assert recon["difference"] == 0.0
        
    # Check all expense accounts
    for exp_name, exp_amt in pl["Expenses"].items():
        dd = get_account_drilldown(db_session, client.id, exp_name)
        assert dd["drilldown_total"] == exp_amt
        recon = reconcile_account(exp_amt, dd["drilldown_total"])
        assert recon["is_reconciled"] is True
        assert recon["difference"] == 0.0

def test_duplicate_journal_entry_deduplication(db_session):
    """
    Test duplicate JE cleanup:
    Verifies that calling cleanup_duplicate_journal_entries purges redundant JEs and restores exact balance.
    """
    client = Client(business_name="Dedup Test Client", fiscal_year_end="December 31", status="Active")
    db_session.add(client)
    db_session.commit()
    bank_acc = ClientBankAccount(client_id=client.id, account_name="Bank", account_type="Bank")
    db_session.add(bank_acc)
    db_session.commit()
    
    tx = Transaction(client_id=client.id, account_id=bank_acc.id, date=datetime(2026, 2, 1), original_description="Shop", cleaned_description="SHOP", category="Repairs", amount=-500.0)
    db_session.add(tx)
    db_session.commit()
    
    # Post first JE
    post_transaction_to_gl(db_session, tx)
    
    # Manually create a duplicate JE simulating legacy corrupted database state
    je2 = JournalEntry(client_id=client.id, transaction_id=tx.id, date=tx.date, description=tx.cleaned_description)
    db_session.add(je2)
    db_session.commit()
    jl2 = JournalLine(journal_entry_id=je2.id, account_name="Repairs", debit=500.0, credit=0.0)
    db_session.add(jl2)
    db_session.commit()
    
    assert db_session.query(JournalEntry).filter(JournalEntry.transaction_id == tx.id).count() == 2
    
    # Run cleanup
    cleaned = cleanup_duplicate_journal_entries(db_session, client.id)
    assert cleaned == 1
    assert db_session.query(JournalEntry).filter(JournalEntry.transaction_id == tx.id).count() == 1
    
    pl = compile_income_statement(db_session, client.id)
    assert pl["Expenses"]["Repairs"] == 500.0
