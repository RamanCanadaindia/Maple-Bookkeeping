import streamlit as st
import pandas as pd
from services.client_service import get_clients
from services.audit_service import get_recent_logs

def render_dashboard(db):
    """
    Renders the firm executive dashboard.
    """
    st.subheader("📊 Firm Operations Dashboard")
    st.markdown("Overview of clients, filing metrics, and systemic audit logging across your accounting practice.")

    # Get data based on user role authorization
    current_user = st.session_state.get("current_user")
    clients = get_clients(db, current_user)
    raw_logs = get_recent_logs(db, limit=100)
    
    # Filter audit logs to only show assigned clients
    role = getattr(current_user, "role", "Viewer")
    if role in ("Admin", "Accountant", "Viewer"):
        audit_logs = raw_logs[:20]
    elif role == "Bookkeeper":
        from core.models import UserClientAccess
        allowed_ids = [r[0] for r in db.query(UserClientAccess.client_id).filter(UserClientAccess.user_id == current_user.id).all()]
        audit_logs = [log for log in raw_logs if log.client_id in allowed_ids][:20]
    elif role == "Client":
        audit_logs = [log for log in raw_logs if log.client_id == current_user.client_id][:20]
    else:
        audit_logs = []
    
    # 1. Summary Metrics Card
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    
    locked_count = sum(1 for c in clients if c.status == "Locked")
    active_count = len(clients) - locked_count
    
    col_m1.metric("Active Clients", f"{active_count}")
    col_m2.metric("Locked Accounts", f"{locked_count}")
    col_m3.metric("Pending Statements", "3 (Surrey Auto, Delta Cafe)")
    col_m4.metric("GST Submissions Due", "2 (Quarterly)")

    # 2. Client Registry Directory
    st.write("")
    st.subheader("🏢 Client Profiles Registry")
    
    if not clients:
        st.info("No client accounts registered in the database yet. Go to Client Management to create one.")
    else:
        # Build pandas DataFrame for display
        client_data = []
        for c in clients:
            client_data.append({
                "Business Name": c.business_name,
                "CRA Business Number": c.business_number or "N/A",
                "GST Number": c.gst_number or "N/A",
                "Filing Period": f"{c.gst_method} ({c.gst_period})",
                "Fiscal Year End": c.fiscal_year_end,
                "Industry": c.industry or "N/A",
                "Status": "🔒 Locked" if c.status == "Locked" else "🟢 Active"
            })
            
        df_clients = pd.DataFrame(client_data)
        st.dataframe(df_clients, use_container_width=True)

    # 3. Systemic Audit Trail
    st.write("")
    st.subheader("📜 Real-Time Audit Log Trail")
    
    if not audit_logs:
        st.info("Audit log is currently empty.")
    else:
        log_data = []
        for log in audit_logs:
            log_data.append({
                "Timestamp (UTC)": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "User Account": log.user_name,
                "Action Performed": log.action_type,
                "Client Association": log.client_name or "Global System",
                "Log Details / Changes": log.details or ""
            })
            
        df_logs = pd.DataFrame(log_data)
        st.dataframe(df_logs, use_container_width=True)
