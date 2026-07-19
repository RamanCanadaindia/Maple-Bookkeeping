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
    Seeds or updates the administrator and default login users.
    Allows overriding/changing credentials via Streamlit Secrets.
    """
    try:
        admin_email = st.secrets.get("APP_ADMIN_EMAIL", "admin@firm.ca")
        admin_password = st.secrets.get("APP_ADMIN_PASSWORD", "admin123")
        admin_name = st.secrets.get("APP_ADMIN_NAME", "System Admin")
    except FileNotFoundError:
        admin_email = os.getenv("APP_ADMIN_EMAIL", "admin@firm.ca")
        admin_password = os.getenv("APP_ADMIN_PASSWORD", "admin123")
        admin_name = os.getenv("APP_ADMIN_NAME", "System Admin")
        
    if not admin_email or not admin_password:
        return
        
    # Check if admin user already exists
    existing = db.query(User).filter(User.email == admin_email.strip().lower()).first()
    if not existing:
        create_user(db, admin_name, admin_email, admin_password, "Admin")
    else:
        # Update password if it doesn't match secrets (e.g. user updated secrets online)
        if not verify_password(admin_password, existing.password_hash):
            existing.password_hash = hash_password(admin_password)
            db.commit()
            
    # Also seed other standard accounts if we are using the default admin account
    if admin_email == "admin@firm.ca":
        # Only seed if not already present
        if not db.query(User).filter(User.email == "accountant@firm.ca").first():
            create_user(db, "Lead Accountant", "accountant@firm.ca", "accountant123", "Accountant")
        if not db.query(User).filter(User.email == "viewer@firm.ca").first():
            create_user(db, "Client Auditor", "viewer@firm.ca", "viewer123", "Viewer")
