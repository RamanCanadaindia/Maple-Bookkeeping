import streamlit as st
from core.database import engine, SessionLocal, Base
from services.auth_service import seed_default_users
from ui.login_view import render_login
from ui.dashboard_view import render_dashboard
from ui.client_view import render_client_management
from ui.statement_import_view import render_statement_import
from ui.reports_view import render_reports
from ui.ledger_view import render_ledger_editor
from ui.receipt_view import render_receipt_matcher

# Setup Page configurations
st.set_page_config(
    page_title="Maple Ledger AI - Canadian Bookkeeping Suite",
    page_icon="🍁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Design Styles (CSS) for a beautiful, premium visual experience
st.markdown(
    """
    <style>
    /* Styling headings and cards */
    .stApp {
        background-color: #fcfcfc;
    }
    .main-header {
        font-size: 2.2rem !important;
        font-weight: 700;
        color: #1e3d59;
        margin-bottom: 0.5rem;
    }
    .user-badge {
        background-color: #e8f1f5;
        color: #1e3d59;
        padding: 0.4rem 0.8rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #d0e1ec;
    }
    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 600;
    }
    .job-card {
        padding: 1.5rem;
        background: #ffffff;
        border-radius: 8px;
        border: 1px solid #e1e8ed;
        margin-bottom: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Initialize Database and Tables only after confirming the engine is PostgreSQL
if engine.dialect.name == "postgresql":
    Base.metadata.create_all(bind=engine)


def seed_default_client(db_session):
    from core.models import Client, ClientBankAccount
    if db_session.query(Client).count() == 0:
        client = Client(
            business_name="Raman Bookkeeping Demo Client",
            business_number="987654321",
            gst_number="987654321RT0001",
            fiscal_year_end="December 31",
            accounting_method="Accrual",
            gst_method="Regular",
            gst_period="Quarterly",
            status="Active"
        )
        db_session.add(client)
        db_session.commit()
        db_session.refresh(client)
        
        # Add Vancity Checking bank account
        vancity_acc = ClientBankAccount(
            client_id=client.id,
            account_name="Vancity Checking",
            account_type="Bank",
            opening_balance=0.0
        )
        db_session.add(vancity_acc)
        
        # Add RBC Mastercard bank account
        rbc_acc = ClientBankAccount(
            client_id=client.id,
            account_name="RBC Mastercard",
            account_type="Credit Card",
            opening_balance=0.0
        )
        db_session.add(rbc_acc)
        db_session.commit()

# Open db session
db = SessionLocal()
try:
    # Seed default test users & demo client
    seed_default_users(db)
    seed_default_client(db)
finally:
    db.close()

# Session State Initialization (Auto-login enabled to make authentication optional)
if "authenticated" not in st.session_state:
    st.session_state.authenticated = True
if "current_user_name" not in st.session_state:
    st.session_state.current_user_name = "Raman Bookkeeping"
if "current_user_role" not in st.session_state:
    st.session_state.current_user_role = "Admin"
if "current_user_email" not in st.session_state:
    st.session_state.current_user_email = "beedhtaxservices@gmail.com"
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# Application Routing Layout
db_session = SessionLocal()

try:
    if not st.session_state.authenticated:
        render_login(db_session)
    else:
        # Authenticated Session View
        with st.sidebar:
            st.markdown("### 🍁 Maple Ledger AI")
            st.write(f"Logged in as:")
            st.markdown(f"<span class='user-badge'>👤 {st.session_state.current_user_name} ({st.session_state.current_user_role})</span>", unsafe_allow_html=True)
            st.write("")
            st.write(f"Email: `{st.session_state.current_user_email}`")
            
            st.write("---")
            if st.button("🚪 Sign Out", type="secondary", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.current_user = None
                st.rerun()
                
        # Main Title bar
        st.markdown("<h1 class='main-header'>🍁 Canadian Bookkeeping Operations</h1>", unsafe_allow_html=True)
        
        # Tabs for Operations
        tab_dash, tab_clients, tab_import, tab_ledger, tab_receipt, tab_reports = st.tabs(["📊 Operations Dashboard", "📁 Client Management", "📥 Statement Ingestion", "📖 General Ledger", "🧾 Receipt Matcher", "📈 Financial Statements"])
        
        with tab_dash:
            render_dashboard(db_session)
            
        with tab_clients:
            render_client_management(db_session)
            
        with tab_import:
            render_statement_import(db_session)
            
        with tab_ledger:
            render_ledger_editor(db_session)
            
        with tab_receipt:
            render_receipt_matcher(db_session)
            
        with tab_reports:
            render_reports(db_session)
            
finally:
    db_session.close()
