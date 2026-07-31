import os
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL - defaults to local SQLite, but can be overridden by secrets or environment variables
DATABASE_URL = None
try:
    if "DATABASE_URL" in st.secrets:
        DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    pass

if not DATABASE_URL:
    DATABASE_URL = os.getenv("DATABASE_URL")

IS_POSTGRES = False
if DATABASE_URL:
    IS_POSTGRES = True
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounting.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"

# Connection pool configurations
if IS_POSTGRES:
    # Normalize URL scheme for PostgreSQL
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        connect_args={"sslmode": "require", "connect_timeout": 10}
    )
    
    # Test connection on startup
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise RuntimeError(
            "Database Connection Error: Failed to connect to the configured PostgreSQL/Supabase database. "
            "Please check your credentials and network settings."
        ) from None
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

def get_database_status():
    """
    Returns the safe database connection status.
    """
    if IS_POSTGRES:
        return "PostgreSQL/Supabase"
    return "Local SQLite"



def check_and_update_schema(db_engine):
    from sqlalchemy import text
    try:
        with db_engine.begin() as conn:
            conn.execute(text("SELECT email_service_provider FROM reminder_settings LIMIT 1"))
    except Exception:
        print("[Schema Update] Adding Resend integration columns to reminder_settings table...")
        try:
            with db_engine.begin() as conn:
                conn.execute(text("ALTER TABLE reminder_settings ADD COLUMN email_service_provider VARCHAR(50) DEFAULT 'GMAIL'"))
                conn.execute(text("ALTER TABLE reminder_settings ADD COLUMN resend_api_key TEXT NULL"))
                conn.execute(text("ALTER TABLE reminder_settings ADD COLUMN resend_from_email VARCHAR(255) NULL"))
        except Exception as e:
            print(f"[Schema Update Error] Could not alter table: {e}")

    # Check client_id in users
    try:
        with db_engine.begin() as conn:
            conn.execute(text("SELECT client_id FROM users LIMIT 1"))
    except Exception:
        print("[Schema Update] Adding client_id column to users table...")
        try:
            with db_engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN client_id INTEGER NULL"))
        except Exception as e:
            print(f"[Schema Update Error] Could not add client_id column: {e}")

    # Check user_client_access table
    try:
        with db_engine.begin() as conn:
            conn.execute(text("SELECT 1 FROM user_client_access LIMIT 1"))
    except Exception:
        print("[Schema Update] Creating user_client_access table...")
        try:
            with db_engine.begin() as conn:
                if "postgresql" in str(db_engine.url):
                    conn.execute(text("""
                        CREATE TABLE user_client_access (
                            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                            PRIMARY KEY (user_id, client_id)
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE user_client_access (
                            user_id INTEGER NOT NULL,
                            client_id INTEGER NOT NULL,
                            PRIMARY KEY (user_id, client_id),
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
                        )
                    """))
        except Exception as e:
            print(f"[Schema Update Error] Could not create user_client_access table: {e}")

# Run schema update on import
check_and_update_schema(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """
    Dependency helper to acquire a thread-safe database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
