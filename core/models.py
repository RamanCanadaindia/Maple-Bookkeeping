from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="Accountant")  # Admin, Accountant, Viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")


class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String, unique=True, index=True, nullable=False)
    business_number = Column(String, nullable=True)  # 9-digit CRA Business Number
    gst_number = Column(String, nullable=True)       # e.g., 123456789RT0001
    fiscal_year_end = Column(String, nullable=False) # e.g. "December 31"
    industry = Column(String, nullable=True)         # e.g. "Consulting", "Real Estate"
    accounting_method = Column(String, default="Accrual") # Cash or Accrual
    business_use_pct = Column(Float, default=100.0)  # For vehicles/mixed assets
    gst_method = Column(String, default="Regular")   # Regular or Quick Method
    gst_period = Column(String, default="Quarterly") # Monthly, Quarterly, Annually
    shareholder_info = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="Active")        # Active, Locked
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    bank_accounts = relationship("ClientBankAccount", back_populates="client", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="client")


class ClientBankAccount(Base):
    __tablename__ = "client_bank_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    account_name = Column(String, nullable=False)     # e.g. "TD Checking", "RBC Mastercard"
    account_number = Column(String, nullable=True)    # e.g. last 4 digits
    account_type = Column(String, nullable=False)     # Bank, Credit Card, Shareholder Loan, Loan
    opening_balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="bank_accounts")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    action_type = Column(String, nullable=False)       # Create Client, Lock Client, Edit Balance
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    client_name = Column(String, nullable=True)
    details = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    client = relationship("Client", back_populates="audit_logs")


class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("client_bank_accounts.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    original_description = Column(String, nullable=False)
    cleaned_description = Column(String, nullable=False)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)  # Positive for credit (deposit), Negative for debit (withdrawal)
    balance = Column(Float, default=0.0)
    ref_number = Column(String, nullable=True)
    
    category = Column(String, nullable=True)
    confidence = Column(Float, default=1.0)  # 1.0 = Rules-based; AI uses 0.0 to 1.0
    
    is_duplicate = Column(Boolean, default=False)
    is_transfer = Column(Boolean, default=False)
    transfer_linked_acc = Column(String, nullable=True)
    review_required = Column(Boolean, default=False)
    
    # GST / Tax Tracking Fields
    gst_rate = Column(Float, default=0.0)
    gst_amount = Column(Float, default=0.0)
    itc_amount = Column(Float, default=0.0)
    itc_eligible = Column(Boolean, default=True)
    
    # Receipt matching fields
    receipt_path = Column(String, nullable=True)
    receipt_status = Column(String, default="Unmatched")
    
    statement_period = Column(String, nullable=True) # e.g. "2026-06"
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client")
    account = relationship("ClientBankAccount")


class CategoryRule(Base):
    __tablename__ = "category_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    keyword = Column(String, nullable=False)           # Match query (case insensitive)
    category = Column(String, nullable=False)          # Chart of Account
    gst_treatment = Column(String, default="Standard") # Exempt, Zero-Rated, Standard
    itc_eligible = Column(Boolean, default=True)
    business_pct = Column(Float, default=100.0)
    confidence = Column(Float, default=1.0)            # 1.0 = Rule based

    # Relationships
    client = relationship("Client")


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    date = Column(DateTime, nullable=False)
    description = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client")
    transaction = relationship("Transaction")
    lines = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    
    id = Column(Integer, primary_key=True, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False)
    account_name = Column(String, nullable=False)  # Chart of account name
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)

    # Relationships
    entry = relationship("JournalEntry", back_populates="lines")
