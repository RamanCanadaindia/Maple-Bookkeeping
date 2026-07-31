import streamlit as st
import pandas as pd
from services.auth_service import (
    get_all_users,
    create_user,
    update_user_role_and_access,
    delete_user
)
from services.client_service import get_clients
from core.models import UserClientAccess

def render_user_management(db):
    """
    Renders the User & Access Control management tab for Admin accounts.
    """
    # Enforce Admin privilege check
    current_user = st.session_state.get("current_user")
    if not current_user or getattr(current_user, "role", "Viewer") != "Admin":
        st.error("Access Denied: You must be a System Administrator to access User & Access settings.")
        return

    st.subheader("👤 User Accounts & Role-Based Access Control")
    st.markdown("Provision login credentials, set classification roles, and map Bookkeepers or Clients to their authorized client companies.")

    all_users = get_all_users(db)
    all_clients = db.query(UserClientAccess.client_id, UserClientAccess.user_id).all()
    clients_list = get_clients(db)
    client_map = {c.id: c.business_name for c in clients_list}

    # Left side: Users list table, Right side: Actions & creation
    col_list, col_action = st.columns([7, 5])

    with col_list:
        st.markdown("### 📋 Active User Profiles")
        if not all_users:
            st.info("No users registered.")
        else:
            user_table_data = []
            for u in all_users:
                # Resolve client linkages
                link_str = "All Clients (Global)"
                if u.role == "Client":
                    link_str = client_map.get(u.client_id, "None (Unassigned)")
                elif u.role == "Bookkeeper":
                    assigned = [client_map.get(c_id, f"ID:{c_id}") for c_id, u_id in all_clients if u_id == u.id]
                    link_str = ", ".join(assigned) if assigned else "None (Unassigned)"
                elif u.role == "Viewer":
                    link_str = "All Clients (Read-Only)"
                
                user_table_data.append({
                    "ID": u.id,
                    "Name / Account": u.name,
                    "Email / Login": u.email,
                    "Security Role": u.role,
                    "Client Access Scope": link_str
                })
            
            st.dataframe(pd.DataFrame(user_table_data), use_container_width=True, hide_index=True)

    with col_action:
        st.markdown("### ➕ Create User Account")
        with st.form("create_user_form", clear_on_submit=True):
            new_name = st.text_input("Name (e.g. Jane Doe)")
            new_email = st.text_input("Email (e.g. jane@firm.ca)")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["Admin", "Accountant", "Bookkeeper", "Viewer", "Client"])
            
            # Client role assignment selection
            sel_client = None
            if new_role == "Client":
                sel_client = st.selectbox("Assign Client Company", list(client_map.values()), key="new_client_select")
            
            # Bookkeeper assignment selection
            sel_bk_clients = []
            if new_role == "Bookkeeper":
                sel_bk_clients = st.multiselect("Assign Client Companies", list(client_map.values()), key="new_bk_select")
                
            submit_user = st.form_submit_button("Create User Profile", use_container_width=True)
            
            if submit_user:
                if not new_name or not new_email or not new_password:
                    st.error("Name, email, and password are required.")
                elif new_role == "Client" and not sel_client:
                    st.error("You must assign a client company for the Client role.")
                else:
                    # Create core user
                    user = create_user(db, new_name, new_email, new_password, new_role)
                    if not user:
                        st.error("Account already exists with this email.")
                    else:
                        # Update access mapping
                        c_id = [k for k, v in client_map.items() if v == sel_client][0] if sel_client else None
                        bk_ids = [k for k, v in client_map.items() if v in sel_bk_clients]
                        
                        update_user_role_and_access(db, user.id, new_role, c_id, bk_ids)
                        st.success(f"Successfully created user account '{new_name}'!")
                        st.rerun()

        st.write("")
        st.markdown("### ⚙️ Edit User Permissions & Role")
        
        edit_user_options = {f"{u.name} ({u.email})": u.id for u in all_users if u.id != current_user.id}
        if not edit_user_options:
            st.info("No other user profiles to manage.")
        else:
            selected_edit_label = st.selectbox("Select User Profile", list(edit_user_options.keys()), key="edit_user_select")
            selected_edit_id = edit_user_options[selected_edit_label]
            selected_user = db.query(UserClientAccess).filter(UserClientAccess.user_id == selected_edit_id).all()
            user_obj = [u for u in all_users if u.id == selected_edit_id][0]
            
            edit_role = st.selectbox("Role Classification", ["Admin", "Accountant", "Bookkeeper", "Viewer", "Client"], index=["Admin", "Accountant", "Bookkeeper", "Viewer", "Client"].index(user_obj.role), key="edit_role_select")
            
            edit_sel_client = None
            if edit_role == "Client":
                curr_c_name = client_map.get(user_obj.client_id, list(client_map.values())[0]) if client_map else None
                edit_sel_client = st.selectbox("Assign Client Company", list(client_map.values()), index=list(client_map.values()).index(curr_c_name) if curr_c_name in client_map.values() else 0, key="edit_client_select")
                
            edit_sel_bk_clients = []
            if edit_role == "Bookkeeper":
                curr_assigned = [client_map[c.client_id] for c in selected_user if c.client_id in client_map]
                edit_sel_bk_clients = st.multiselect("Assign Client Companies", list(client_map.values()), default=curr_assigned, key="edit_bk_select")
                
            col_save, col_del = st.columns(2)
            
            with col_save:
                if st.button("💾 Save Settings", use_container_width=True):
                    c_id = [k for k, v in client_map.items() if v == edit_sel_client][0] if edit_sel_client else None
                    bk_ids = [k for k, v in client_map.items() if v in edit_sel_bk_clients]
                    update_user_role_and_access(db, selected_edit_id, edit_role, c_id, bk_ids)
                    st.success("Successfully updated user permissions!")
                    st.rerun()
                    
            with col_del:
                if st.button("🗑️ Delete Account", type="primary", use_container_width=True):
                    delete_user(db, selected_edit_id)
                    st.success("Successfully deleted user profile.")
                    st.rerun()
