from sqlalchemy.orm import Session
from core.models import Client, ClientBankAccount
from services.audit_service import log_action
import logging

logger = logging.getLogger("ClientService")

def get_clients(db: Session):
    """
    Retrieves all client records from the database.
    """
    return db.query(Client).all()

def get_client_by_id(db: Session, client_id: int) -> Client:
    """
    Retrieves a single client profile by ID.
    """
    return db.query(Client).filter(Client.id == client_id).first()

def create_client(
    db: Session,
    business_name: str,
    business_number: str,
    gst_number: str,
    fiscal_year_end: str,
    industry: str,
    accounting_method: str = "Accrual",
    business_use_pct: float = 100.0,
    gst_method: str = "Regular",
    gst_period: str = "Quarterly",
    shareholder_info: str = None,
    notes: str = None,
    current_user_name: str = "System"
) -> Client:
    """
    Creates a new client and logs the action to the audit logs.
    """
    existing = db.query(Client).filter(Client.business_name == business_name.strip()).first()
    if existing:
        raise ValueError("A client with this business name already exists.")

    client = Client(
        business_name=business_name.strip(),
        business_number=business_number.strip() if business_number else None,
        gst_number=gst_number.strip() if gst_number else None,
        fiscal_year_end=fiscal_year_end,
        industry=industry,
        accounting_method=accounting_method,
        business_use_pct=business_use_pct,
        gst_method=gst_method,
        gst_period=gst_period,
        shareholder_info=shareholder_info,
        notes=notes,
        status="Active"
    )
    
    db.add(client)
    db.commit()
    db.refresh(client)
    
    log_action(
        db,
        user_id=None,
        user_name=current_user_name,
        action_type="Create Client",
        client_id=client.id,
        client_name=client.business_name,
        details=f"CRA BN: {client.business_number} | GST Mode: {client.gst_method} ({client.gst_period})"
    )
    return client

def add_bank_account(
    db: Session,
    client_id: int,
    account_name: str,
    account_number: str,
    account_type: str,
    opening_balance: float = 0.0,
    current_user_name: str = "System"
) -> ClientBankAccount:
    """
    Adds a bank or credit card ledger account map to a client.
    """
    client = get_client_by_id(db, client_id)
    if not client:
        raise ValueError("Client not found.")
        
    if client.status == "Locked":
        raise ValueError("Client profile is locked. Unlocking is required before editing accounts.")

    acc = ClientBankAccount(
        client_id=client_id,
        account_name=account_name.strip(),
        account_number=account_number.strip() if account_number else None,
        account_type=account_type,
        opening_balance=opening_balance
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    
    log_action(
        db,
        user_id=None,
        user_name=current_user_name,
        action_type="Add Bank Account",
        client_id=client_id,
        client_name=client.business_name,
        details=f"Account: {acc.account_name} ({acc.account_type}) | Opening Balance: ${acc.opening_balance:,.2f}"
    )
    return acc

def toggle_client_lock(db: Session, client_id: int, lock: bool, user_role: str, current_user_name: str) -> Client:
    """
    Locks or unlocks a client. Administrators can unlock; anyone can lock.
    """
    client = get_client_by_id(db, client_id)
    if not client:
        raise ValueError("Client not found.")
        
    if not lock and user_role != "Admin":
        raise PermissionError("Only Administrators are authorized to unlock client records.")
        
    client.status = "Locked" if lock else "Active"
    db.commit()
    
    action = "Lock Client" if lock else "Unlock Client"
    log_action(
        db,
        user_id=None,
        user_name=current_user_name,
        action_type=action,
        client_id=client_id,
        client_name=client.business_name,
        details=f"Performed by: {current_user_name} ({user_role})"
    )
    return client
