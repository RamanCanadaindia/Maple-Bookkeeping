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
    role = Column(String, default="Accountant")  # Admin, Accountant, Bookkeeper, Viewer, Client
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")
    client = relationship("Client", foreign_keys=[client_id])


class UserClientAccess(Base):
    __tablename__ = "user_client_access"
    
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)


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
    email = Column(String, nullable=True)
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

    @property
    def description(self):
        return self.cleaned_description or self.original_description

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


class ReminderType(Base):
    __tablename__ = "reminder_types"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    default_days_before = Column(String, default="30,14,7,2") # comma-separated list
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    reminder_type_id = Column(Integer, ForeignKey("reminder_types.id"), nullable=False)
    first_due_date = Column(DateTime, nullable=False)
    current_due_date = Column(DateTime, nullable=False)
    frequency = Column(String, default="Quarterly") # One Time, Monthly, Quarterly, Annually, Custom
    recurrence_interval = Column(Integer, default=1)
    reminder_offsets = Column(String, nullable=False) # comma-separated string e.g. "30,14,7,2"
    template_id = Column(Integer, ForeignKey("email_templates.id"), nullable=True)
    status = Column(String, default="ACTIVE") # ACTIVE, PAUSED, CANCELLED
    notes = Column(Text, nullable=True)
    day_of_month = Column(Integer, nullable=True)
    month_of_year = Column(Integer, nullable=True)
    custom_interval_days = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    client = relationship("Client")
    reminder_type = relationship("ReminderType")
    template = relationship("EmailTemplate", foreign_keys=[template_id])


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id"), nullable=False)
    current_due_date = Column(DateTime, nullable=False)
    offset_days = Column(Integer, nullable=False)
    recipient_email = Column(String, nullable=False)
    template_id = Column(Integer, ForeignKey("email_templates.id"), nullable=True)
    channel = Column(String, default="GMAIL")
    status = Column(String, default="PENDING") # PENDING, PROCESSING, SENT, FAILED, SKIPPED
    scheduled_send_date = Column(DateTime, nullable=False)
    processing_started_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, default=0)
    gmail_message_id = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)

    # Unique Constraint to prevent duplicates
    from sqlalchemy import UniqueConstraint
    __table_args__ = (
        UniqueConstraint(
            'reminder_id', 'current_due_date', 'offset_days', 'recipient_email', 'template_id', 'channel',
            name='uq_notification_identity'
        ),
    )

    # Relationships
    reminder = relationship("Reminder")
    template = relationship("EmailTemplate")


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    reminder_type_id = Column(Integer, ForeignKey("reminder_types.id"), nullable=True)
    name = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body_html = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    reminder_type = relationship("ReminderType")


class EmailHistory(Base):
    __tablename__ = "email_histories"
    
    id = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id"), nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    recipient_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    reminder_type_name = Column(String, nullable=True)
    status = Column(String, default="SENT")
    gmail_message_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    reminder = relationship("Reminder")


class ReminderSettings(Base):
    __tablename__ = "reminder_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    gmail_oauth_token = Column(Text, nullable=True) # JSON encrypted string
    gmail_authorized_email = Column(String, nullable=True)
    email_service_provider = Column(String(50), default="GMAIL") # GMAIL or RESEND
    resend_api_key = Column(Text, nullable=True) # Encrypted string
    resend_from_email = Column(String(255), nullable=True)


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False) # SUCCESS, FAILED
    reminders_checked = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    emails_failed = Column(Integer, default=0)
    error_summary = Column(Text, nullable=True)
    trigger_source = Column(String, default="AUTO") # AUTO, MANUAL
