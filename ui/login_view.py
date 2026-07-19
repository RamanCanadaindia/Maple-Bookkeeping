import streamlit as st
from services.auth_service import authenticate_user

def render_login(db):
    """
    Renders the secure credentials form.
    """
    st.markdown(
        """
        <div style="max-width: 480px; margin: 4rem auto; padding: 2rem; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #eaeaea;">
            <h2 style="text-align: center; color: #1e3d59; margin-bottom: 0.2rem;">🍁 Maple Ledger AI</h2>
            <p style="text-align: center; color: #666; margin-bottom: 2rem; font-size: 0.95rem;">Professional Bookkeeping Engine for Canadian Accounting Firms</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Place standard Streamlit components inside a centered container
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        with st.form("login_form"):
            password = st.text_input("Unlock Password", type="password", placeholder="••••••••")
            
            submit = st.form_submit_button("Unlock Dashboard", use_container_width=True)
            
            if submit:
                if not password:
                    st.error("Please enter your password.")
                else:
                    # Retrieve the configured admin email to authenticate against
                    import os
                    try:
                        admin_email = st.secrets.get("APP_ADMIN_EMAIL", "admin@firm.ca")
                    except FileNotFoundError:
                        admin_email = os.getenv("APP_ADMIN_EMAIL", "admin@firm.ca")
                        
                    user = authenticate_user(db, admin_email, password)
                    if user:
                        st.session_state.authenticated = True
                        st.session_state.current_user = user
                        st.session_state.current_user_name = user.name
                        st.session_state.current_user_role = user.role
                        st.session_state.current_user_email = user.email
                        st.success("Unlocked successfully!")
                        st.rerun()
                    else:
                        st.error("Incorrect password.")
