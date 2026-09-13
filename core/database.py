import os
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL - defaults to local SQLite, but can be overridden by secrets or environment variables
USE_LOCAL = os.getenv("USE_LOCAL_SQLITE", "1") == "1"
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL and not USE_LOCAL:
    try:
        if "DATABASE_URL" in st.secrets:
            DATABASE_URL = st.secrets["DATABASE_URL"]
    except Exception:
        pass

IS_POSTGRES = False
if DATABASE_URL and ("postgres" in DATABASE_URL or "postgresql" in DATABASE_URL):
    IS_POSTGRES = True

if IS_POSTGRES:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
            connect_args={"sslmode": "require", "connect_timeout": 5}
        )
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as pg_err:
        print(f"[Database Warning] PostgreSQL unreachable ({pg_err}). Falling back to local SQLite.")
        IS_POSTGRES = False
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounting.db")
        DATABASE_URL = f"sqlite:///{DB_PATH}"
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False}
        )
else:
    if not DATABASE_URL:
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounting.db")
        DATABASE_URL = f"sqlite:///{DB_PATH}"
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

    # Check email, shareholder_info, notes in clients table
    for col_name, col_type in [("email", "VARCHAR(255) NULL"), ("shareholder_info", "TEXT NULL"), ("notes", "TEXT NULL")]:
        try:
            with db_engine.begin() as conn:
                conn.execute(text(f"SELECT {col_name} FROM clients LIMIT 1"))
        except Exception:
            try:
                with db_engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE clients ADD COLUMN {col_name} {col_type}"))
            except Exception as e:
                print(f"[Schema Update Error] Could not add {col_name} column to clients: {e}")

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

    # Check custom_categories table
    try:
        with db_engine.begin() as conn:
            conn.execute(text("SELECT 1 FROM custom_categories LIMIT 1"))
    except Exception:
        print("[Schema Update] Creating custom_categories table...")
        try:
            with db_engine.begin() as conn:
                if "postgresql" in str(db_engine.url):
                    conn.execute(text("""
                        CREATE TABLE custom_categories (
                            id SERIAL PRIMARY KEY,
                            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                            name VARCHAR NOT NULL
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_custom_categories_id ON custom_categories (id)"))
                else:
                    conn.execute(text("""
                        CREATE TABLE custom_categories (
                            id INTEGER PRIMARY KEY,
                            client_id INTEGER NOT NULL,
                            name VARCHAR NOT NULL,
                            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_custom_categories_id ON custom_categories (id)"))
        except Exception as e:
            print(f"[Schema Update Error] Could not create custom_categories table: {e}")

    # Desktop mapper memory. Kept as an idempotent startup check for existing installs.
    try:
        with db_engine.begin() as conn:
            conn.execute(text("SELECT 1 FROM learned_mappings LIMIT 1"))
    except Exception:
        print("[Schema Update] Creating learned_mappings table...")
        try:
            with db_engine.begin() as conn:
                is_pg = "postgresql" in str(db_engine.url)
                id_type = "SERIAL" if is_pg else "INTEGER"
                bool_default = "TRUE" if is_pg else "1"
                conn.execute(text(f"""
                    CREATE TABLE learned_mappings (
                        id {id_type} PRIMARY KEY,
                        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                        normalized_vendor VARCHAR NOT NULL,
                        sample_description VARCHAR NULL,
                        category VARCHAR NOT NULL,
                        gst_treatment VARCHAR DEFAULT 'Standard',
                        itc_eligible BOOLEAN DEFAULT {bool_default},
                        business_pct FLOAT DEFAULT 100.0,
                        confirmation_count INTEGER DEFAULT 1,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                """))
                conn.execute(text("CREATE INDEX ix_learned_mappings_client_id ON learned_mappings (client_id)"))
                conn.execute(text("CREATE UNIQUE INDEX uq_learned_mapping_vendor ON learned_mappings (client_id, normalized_vendor)"))
        except Exception as e:
            print(f"[Schema Update Error] Could not create learned_mappings table: {e}")

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
