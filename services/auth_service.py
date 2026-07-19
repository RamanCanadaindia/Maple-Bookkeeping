import bcrypt
import os
import streamlit as st
from sqlalchemy.orm import Session
from core.models import User
from services.audit_service import log_action

def hash_password(password: str) -> str:
    """
    Cryptographically hashes a plain password string.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verifies a plain password string against its stored hash.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Authenticates a user. Returns the User model instance if correct, else None.
    Writes details to the audit log trail.
    """
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not user.is_active:
        log_action(db, user_id=None, user_name="Anonymous", action_type="Failed Login", details=f"Attempted email: {email}")
        return None
        
    if verify_password(password, user.password_hash):
        log_action(db, user_id=user.id, user_name=user.name, action_type="Successful Login", details=f"User role: {user.role}")
        return user
    else:
        log_action(db, user_id=None, user_name=user.name, action_type="Failed Login", details=f"Incorrect password for: {email}")
        return None

def create_user(db: Session, name: str, email: str, password: str, role: str = "Accountant") -> User:
    """
    Registers a new system user profile.
    """
    existing_user = db.query(User).filter(User.email == email.strip().lower()).first()
    if existing_user:
        return None
        
    hashed = hash_password(password)
    user = User(
        name=name.strip(),
        email=email.strip().lower(),
        password_hash=hashed,
        role=role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def seed_default_users(db: Session):
    """
    Seeds the default login users if the database is completely empty.
    Allows overriding the administrator email and password via Streamlit Secrets.
    """
    if db.query(User).count() != 0:
        return
        
    try:
        admin_email = st.secrets.get("APP_ADMIN_EMAIL", "admin@firm.ca")
        admin_password = st.secrets.get("APP_ADMIN_PASSWORD", "admin123")
        admin_name = st.secrets.get("APP_ADMIN_NAME", "System Admin")
    except FileNotFoundError:
        admin_email = os.getenv("APP_ADMIN_EMAIL", "admin@firm.ca")
        admin_password = os.getenv("APP_ADMIN_PASSWORD", "admin123")
        admin_name = os.getenv("APP_ADMIN_NAME", "System Admin")
        
    create_user(db, admin_name, admin_email, admin_password, "Admin")
    
    # Seed default staff profiles if using the default admin account
    if admin_email == "admin@firm.ca":
        create_user(db, "Lead Accountant", "accountant@firm.ca", "accountant123", "Accountant")
        create_user(db, "Client Auditor", "viewer@firm.ca", "viewer123", "Viewer")
