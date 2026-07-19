from sqlalchemy.orm import Session
from core.models import AuditLog
from datetime import datetime
import logging

logger = logging.getLogger("AuditLogger")

def log_action(db: Session, user_id: int, user_name: str, action_type: str, client_id: int = None, client_name: str = None, details: str = None):
    """
    Creates and saves a structured record in the system audit trails.
    """
    try:
        log_entry = AuditLog(
            user_id=user_id,
            user_name=user_name,
            timestamp=datetime.utcnow(),
            action_type=action_type,
            client_id=client_id,
            client_name=client_name,
            details=details
        )
        db.add(log_entry)
        db.commit()
        logger.info(f"Audit Logged: {action_type} by {user_name} | Client: {client_name or 'N/A'}")
        return log_entry
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to log audit action: {e}")
        return None

def get_recent_logs(db: Session, limit: int = 50):
    """
    Returns the recent audit logs sorted by newest timestamp.
    """
    return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
