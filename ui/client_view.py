import streamlit as st
import pandas as pd
import re
from services.client_service import (
    get_clients,
    create_client,
    add_bank_account,
    toggle_client_lock
)

def render_client_management(db):
    """
    Renders client registrations, settings forms, ledger accounts, and lock configurations.
    """
    st.subheader("📁 Client Accounts Management")
    
    clients = get_clients(db)
    
    # Left Column: Client List Selection, Right Column: Setup Forms
    col_sel, col_form = st.columns([4, 8])
    
    selected_client_id = None
    
    with col_sel:
        st.markdown("**Client Registry**")
        client_options = {"➕ Register New Client Profile": 0}
        for c in clients:
            status_symbol = "🔒" if c.status == "Locked" else "🟢"
            client_options[f"{status_symbol} {c.business_name}"] = c.id
            
        selected_label = st.radio(
            "Select Client Account", 
            options=list(client_options.keys()), 
            label_visibility="collapsed"
        )
        selected_client_id = client_options[selected_label]
        
    with col_form:
        if selected_client_id == 0:
            # Render Creation Form
            st.subheader("➕ Create Client Profile")
            with st.form("new_client_form"):
                bus_name = st.text_input("Business Legal Name (Required)*")
                
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    bus_num = st.text_input("CRA Business Number (9 Digits)", help="e.g. 123456789")
                    gst_period = st.selectbox("GST/HST Filing Period", ["Monthly", "Quarterly", "Annually"])
                with col_c2:
                    gst_num = st.text_input("GST Number (15 Characters)", help="e.g. 123456789RT0001")
                    gst_method = st.selectbox("GST Accounting Method", ["Regular", "Quick Method"])
                    
                col_c3, col_c4 = st.columns(2)
                with col_c3:
                    fye = st.selectbox(
                        "Fiscal Year End",
                        ["January 31", "February 28", "March 31", "April 30", "May 31", "June 30",
                         "July 31", "August 31", "September 30", "October 31", "November 30", "December 31"]
                    )
                    method = st.selectbox("Accounting Basis", ["Accrual", "Cash"])
                with col_c4:
                    industry = st.selectbox(
                        "Industry Classification",
                        ["Professional Services", "Real Estate & Rental", "Retail / E-commerce",
                         "Construction & Trades", "Automotive & Transport", "Holding Company", "Other"]
                    )
                    use_pct = st.number_input("Default Business Use %", min_value=1.0, max_value=100.0, value=100.0, step=1.0)
                    
                shareholder = st.text_area("Shareholder / Owner Information")
                notes = st.text_area("Bookkeeping / Tax Workflow Notes")
                
                create_submit = st.form_submit_button("Register Client Profile", type="primary", use_container_width=True)
                
                if create_submit:
                    # Validate inputs
                    if not bus_name:
                        st.error("Business Legal Name is a required field.")
                    elif bus_num and not re.match(r'^\d{9}$', bus_num.strip()):
                        st.error("CRA Business Number must be exactly 9 digits.")
                    elif gst_num and not re.match(r'^\d{9}RT\d{4}$', gst_num.strip()):
                        st.error("GST Number must be 15 characters matching CRA format (e.g. 123456789RT0001).")
                    else:
                        try:
                            new_c = create_client(
                                db=db,
                                business_name=bus_name,
                                business_number=bus_num,
                                gst_number=gst_num,
                                fiscal_year_end=fye,
                                industry=industry,
                                accounting_method=method,
                                business_use_pct=use_pct,
                                gst_method=gst_method,
                                gst_period=gst_period,
                                shareholder_info=shareholder,
                                notes=notes,
                                current_user_name=st.session_state.get("current_user_name", "System")
                            )
                            st.success(f"Successfully registered client: {new_c.business_name}!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to create client: {e}")
        else:
            # Render Client Profile Management View
            client = next(c for c in clients if c.id == selected_client_id)
            
            st.title(f"🏢 {client.business_name}")
            
            # Displays state badge
            if client.status == "Locked":
                st.error("🔒 THIS CLIENT PROFILE IS LOCKED. Bookkeeping and account configurations are read-only.")
            else:
                st.success("🟢 THIS CLIENT PROFILE IS ACTIVE. Bookkeeping transactions and bank setups can be edited.")
                
            tab_info, tab_ledgers, tab_lock = st.tabs(["📋 Business Profile", "🏦 Linked Bank Accounts", "🛡️ Lock Management"])
            
            with tab_info:
                st.subheader("General Profile Information")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.write(f"**Business Legal Name:** {client.business_name}")
                    st.write(f"**CRA Business Number:** {client.business_number or 'N/A'}")
                    st.write(f"**GST/HST Number:** {client.gst_number or 'N/A'}")
                    st.write(f"**GST Method:** {client.gst_method} ({client.gst_period})")
                with col_d2:
                    st.write(f"**Fiscal Year End:** {client.fiscal_year_end}")
                    st.write(f"**Accounting Method:** {client.accounting_method}")
                    st.write(f"**Industry Classification:** {client.industry or 'N/A'}")
                    st.write(f"**Default Business Use %:** {client.business_use_pct}%")
                    
                st.write("")
                st.write("**Shareholder Information:**")
                st.write(client.shareholder_info or "No shareholder info documented.")
                st.write("**Accountant Notes:**")
                st.write(client.notes or "No notes documented.")
                
                # Client Backup Section
                st.write("")
                st.markdown("---")
                st.markdown("##### 📥 Backup & Portability")
                st.write("Generate and download a complete portability backup containing this client's profile information, linked financial accounts, keyword mapping rules, and transaction history.")
                
                import json
                from core.models import CategoryRule, Transaction
                category_rules = db.query(CategoryRule).filter(CategoryRule.client_id == client.id).all()
                transactions = db.query(Transaction).filter(Transaction.client_id == client.id).all()
                
                backup_dict = {
                    "client": {
                        "business_name": client.business_name,
                        "business_number": client.business_number,
                        "gst_number": client.gst_number,
                        "fiscal_year_end": client.fiscal_year_end,
                        "accounting_method": client.accounting_method,
                        "industry": client.industry,
                        "business_use_pct": client.business_use_pct,
                        "gst_method": client.gst_method,
                        "gst_period": client.gst_period,
                        "shareholder_info": client.shareholder_info,
                        "notes": client.notes,
                        "status": client.status
                    },
                    "bank_accounts": [
                        {
                            "account_name": a.account_name,
                            "account_number": a.account_number,
                            "account_type": a.account_type,
                            "opening_balance": a.opening_balance
                        } for a in client.bank_accounts
                    ],
                    "category_rules": [
                        {
                            "keyword": r.keyword,
                            "category": r.category,
                            "gst_treatment": r.gst_treatment,
                            "itc_eligible": r.itc_eligible,
                            "business_pct": r.business_pct
                        } for r in category_rules
                    ],
                    "transactions": [
                        {
                            "date": t.date.strftime("%Y-%m-%d"),
                            "original_description": t.original_description,
                            "cleaned_description": t.cleaned_description,
                            "amount": t.amount,
                            "category": t.category,
                            "gst_amount": t.gst_amount,
                            "itc_amount": t.itc_amount,
                            "bank_account_name": t.account.account_name if t.account else None
                        } for t in transactions
                    ]
                }
                backup_json = json.dumps(backup_dict, indent=2)
                st.download_button(
                    label="📥 Download Client Backup (.json)",
                    data=backup_json,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_backup.json",
                    mime="application/json",
                    use_container_width=True,
                    key=f"dl_backup_json_{client.id}"
                )
                
            with tab_ledgers:
                st.subheader("Linked Financial Ledger Accounts")
                
                # Render list of current accounts
                if not client.bank_accounts:
                    st.info("No bank accounts, credit cards, or loan accounts mapped to this client yet.")
                else:
                    acc_records = []
                    for acc in client.bank_accounts:
                        acc_records.append({
                            "AccountID": acc.id,
                            "Account Name": acc.account_name,
                            "Account Number (Last 4)": acc.account_number or "",
                            "Account Type": acc.account_type,
                            "Opening Balance ($ CAD)": acc.opening_balance
                        })
                    df_accs = pd.DataFrame(acc_records)
                    
                    edited_accs_df = st.data_editor(
                        df_accs,
                        column_config={
                            "AccountID": st.column_config.NumberColumn("ID", disabled=True),
                            "Account Name": st.column_config.TextColumn("Account Name"),
                            "Account Number (Last 4)": st.column_config.TextColumn("Account Number (Last 4)", max_chars=4),
                            "Account Type": st.column_config.SelectboxColumn(
                                "Account Type",
                                options=["Bank", "Credit Card", "Shareholder Loan", "Loan"],
                                required=True
                            ),
                            "Opening Balance ($ CAD)": st.column_config.NumberColumn("Opening Balance ($ CAD)", format="$%.2f")
                        },
                        disabled=["AccountID"],
                        num_rows="dynamic",
                        use_container_width=True,
                        key="client_accounts_data_editor"
                    )
                    
                    # 1. Catch account deletions
                    accs_editor_state = st.session_state.get("client_accounts_data_editor", {})
                    if accs_editor_state and "deleted_rows" in accs_editor_state and accs_editor_state["deleted_rows"]:
                        deleted_indices = accs_editor_state["deleted_rows"]
                        with st.spinner("Deleting selected bank/credit card account(s) and clearing transaction logs..."):
                            from core.models import ClientBankAccount, Transaction, JournalEntry, JournalLine
                            for idx in deleted_indices:
                                acc_id = int(df_accs.iloc[idx]["AccountID"])
                                db_acc = db.query(ClientBankAccount).filter(ClientBankAccount.id == acc_id).first()
                                if db_acc:
                                    txs_to_del = db.query(Transaction).filter(Transaction.account_id == acc_id).all()
                                    for t in txs_to_del:
                                        je = db.query(JournalEntry).filter(JournalEntry.transaction_id == t.id).first()
                                        if je:
                                            db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).delete(synchronize_session=False)
                                            db.delete(je)
                                        db.delete(t)
                                    db.delete(db_acc)
                            db.commit()
                        st.toast("Deleted account(s) and associated transactions successfully!", icon="🗑️")
                        st.rerun()
                        
                    # 2. Catch account edits
                    for index, row in edited_accs_df.iterrows():
                        acc_id = int(row["AccountID"])
                        orig = df_accs.iloc[index]
                        
                        if (row["Account Name"] != orig["Account Name"] or
                            row["Account Number (Last 4)"] != orig["Account Number (Last 4)"] or
                            row["Account Type"] != orig["Account Type"] or
                            row["Opening Balance ($ CAD)"] != orig["Opening Balance ($ CAD)"]):
                            
                            from core.models import ClientBankAccount, AuditLog
                            db_acc = db.query(ClientBankAccount).filter(ClientBankAccount.id == acc_id).first()
                            if db_acc:
                                details = f"Updated Account ID {acc_id}: '{db_acc.account_name}' -> '{row['Account Name']}', Type '{db_acc.account_type}' -> '{row['Account Type']}'"
                                log = AuditLog(
                                    user_name=st.session_state.get("current_user_name", "System"),
                                    action_type="Edit Account",
                                    client_id=client.id,
                                    client_name=client.business_name,
                                    details=details
                                )
                                db.add(log)
                                
                                db_acc.account_name = row["Account Name"]
                                db_acc.account_number = row["Account Number (Last 4)"]
                                db_acc.account_type = row["Account Type"]
                                db_acc.opening_balance = float(row["Opening Balance ($ CAD)"])
                                
                                db.commit()
                                st.toast(f"Updated account '{row['Account Name']}' successfully!", icon="✅")
                                st.rerun()
                    
                st.write("")
                st.subheader("➕ Map New Bank/Credit Card Ledger Account")
                
                if client.status == "Locked":
                    st.warning("Locked profiles cannot link new accounts. Unlock this client to proceed.")
                else:
                    with st.form("bank_account_form"):
                        acc_name = st.text_input("Account Name (e.g. TD Business Checking)*")
                        col_a1, col_a2 = st.columns(2)
                        with col_a1:
                            acc_type = st.selectbox("Account Type", ["Bank", "Credit Card", "Shareholder Loan", "Loan"])
                            acc_num = st.text_input("Account Number (Last 4 Digits)", max_chars=4)
                        with col_a2:
                            op_bal = st.number_input("Opening Balance ($ CAD)", value=0.0, step=100.0)
                            
                        submit_acc = st.form_submit_button("Link Account", use_container_width=True)
                        if submit_acc:
                            if not acc_name:
                                st.error("Account Name is required.")
                            elif acc_num and not re.match(r'^\d{4}$', acc_num.strip()):
                                st.error("Account Number must be exactly 4 digits.")
                            else:
                                try:
                                    add_bank_account(
                                        db=db,
                                        client_id=client.id,
                                        account_name=acc_name,
                                        account_number=acc_num,
                                        account_type=acc_type,
                                        opening_balance=op_bal,
                                        current_user_name=st.session_state.get("current_user_name", "System")
                                    )
                                    st.success(f"Linked ledger account {acc_name} successfully!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to link account: {e}")
                                    
            with tab_lock:
                st.subheader("Audit & Lock Management")
                
                user_role = st.session_state.get("current_user_role", "Viewer")
                user_name = st.session_state.get("current_user_name", "Anonymous")
                
                if client.status == "Active":
                    st.write("Locking this client prevents changes to their bank configurations and bookkeeping files.")
                    lock_btn = st.button("🔒 Lock Client Profile", type="primary", use_container_width=True)
                    if lock_btn:
                        toggle_client_lock(db, client.id, lock=True, user_role=user_role, current_user_name=user_name)
                        st.success("Client profile locked successfully!")
                        st.rerun()
                else:
                    st.write("Unlocking this client allows accountants to resume modifications. **Requires Administrator privileges.**")
                    unlock_btn = st.button("🔓 Unlock Client Profile", type="primary", use_container_width=True)
                    if unlock_btn:
                        try:
                            toggle_client_lock(db, client.id, lock=False, user_role=user_role, current_user_name=user_name)
                            st.success("Client profile unlocked successfully!")
                            st.rerun()
                        except PermissionError as pe:
                            st.error(f"Access Denied: {pe}")
