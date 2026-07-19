import streamlit as st
import pandas as pd
from services.client_service import get_clients, get_client_by_id
from services.ledger_service import update_transaction_category, update_transaction_gst_manual
from services.ai_service import suggest_merchant_category, VALID_CATEGORIES
from services.rule_service import get_client_rules, create_category_rule, match_local_rules
from core.models import Transaction, CategoryRule, ClientBankAccount

def render_ledger_editor(db):
    """
    Renders the General Ledger transaction browser, Bank Reconciliation engine, and Rules manager.
    """
    st.subheader("📖 General Ledger Account Browser")
    
    clients = get_clients(db)
    if not clients:
        st.warning("Please create a client profile before accessing the General Ledger.")
        return
        
    # Select Client Account at the top level
    client_options = {c.business_name: c.id for c in clients}
    client_name = st.selectbox("Client Account", list(client_options.keys()), key="ledger_client_select")
    client_id = client_options[client_name]
    client = get_client_by_id(db, client_id)
    
    # Query Posted Transactions (Sorted by ID Ascending to preserve import sequence)
    txs = db.query(Transaction).filter(Transaction.client_id == client_id).order_by(Transaction.id.asc()).all()
    
    # Instantiate the three workspace tabs
    tab_reclass, tab_recon, tab_tx_cat = st.tabs([
        "✏️ Reclassify & Edit Ledger", 
        "⚖️ Bank Account Reconciliation",
        "📂 Transactions by Category"
    ])
    
    # ----------------------------------------------------
    # TAB 1: Reclassify & Edit Ledger
    # ----------------------------------------------------
    with tab_reclass:
        if not txs:
            st.info("No transaction records found. Upload a bank statement in the Statement Ingestion tab first.")
        else:
            st.markdown("### Transaction Editor")
            st.info("💡 **Tips:**\n"
                    "*   Double-click the **Category** cell in any row to change its mapping.\n"
                    "*   Select a row and press the **Delete** key (or click the trash icon) to delete a wrong transaction.")
            
            # Double filter columns
            col_f1, col_f2 = st.columns(2)
            
            with col_f1:
                categories_present = sorted(list(set(t.category or ("Suspense Revenue" if t.amount > 0 else "Suspense Expense") for t in txs)))
                filter_options = ["All Categories"] + categories_present
                selected_filter = st.selectbox("🔍 Filter by Category", filter_options, index=0, key="ledger_category_filter")
                
            # Build Bank Names Map
            bank_names = {}
            bank_options = {"All Accounts": 0}
            for a in db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all():
                type_lbl = "Bank Checking" if a.account_type.lower() == "bank" else "Credit Card"
                bank_names[a.id] = f"{a.account_name} ({type_lbl})"
                bank_options[f"{a.account_name} ({type_lbl})"] = a.id
                
            with col_f2:
                selected_bank_filter = st.selectbox("🏦 Filter by Bank Account", list(bank_options.keys()), index=0, key="ledger_bank_filter")
            
            # Build Grid Data
            grid_data = []
            for t in txs:
                cat = t.category or ("Suspense Revenue" if t.amount > 0 else "Suspense Expense")
                
                # Apply Category filter
                if selected_filter != "All Categories" and cat != selected_filter:
                    continue
                    
                # Apply Bank Account filter
                if selected_bank_filter != "All Accounts":
                    target_bank_id = bank_options[selected_bank_filter]
                    if t.account_id != target_bank_id:
                        continue
                        
                grid_data.append({
                    "Select": st.session_state.get("ledger_select_all", False),
                    "TxID": t.id,
                    "Account": bank_names.get(t.account_id, "Unknown"),
                    "Date": t.date.strftime("%Y-%m-%d"),
                    "Original Memo": t.original_description,
                    "Merchant": t.cleaned_description,
                    "Withdrawal / Expense ($)": abs(t.amount) if t.amount < 0 else None,
                    "Deposit / Income ($)": t.amount if t.amount > 0 else None,
                    "Category": cat,
                    "GST ($)": t.gst_amount or 0.0,
                    "Claimed ITC ($)": t.itc_amount or 0.0,
                    "RawAmount": t.amount  # kept for summary logic
                })
                
            df = pd.DataFrame(grid_data)
            
            # 📊 Category Summary totals for all accounts combined
            if not df.empty:
                with st.expander("📊 Category Totals Summary (All Accounts)", expanded=False):
                    summary_rows = []
                    for c_name in sorted(list(set(df["Category"]))):
                        df_sub = df[df["Category"] == c_name]
                        summary_rows.append({
                            "Category": c_name,
                            "Total Amount": df_sub["RawAmount"].sum(),
                            "Transaction Count": len(df_sub)
                        })
                    df_summary = pd.DataFrame(summary_rows)
                    st.dataframe(
                        df_summary,
                        column_config={
                            "Category": st.column_config.TextColumn("Category"),
                            "Total Amount": st.column_config.NumberColumn("Total Amount", format="$%.2f"),
                            "Transaction Count": st.column_config.NumberColumn("Transaction Count")
                        },
                        use_container_width=True,
                        hide_index=True
                    )
            
            # Display Category Totals & Metrics
            if not df.empty:
                total_sum = df["RawAmount"].sum()
                tx_count = len(df)
                
                # Render 4-column summary metrics
                col_met1, col_met2, col_met3, col_met4 = st.columns(4)
                with col_met1:
                    sum_withdrawals = df["Withdrawal / Expense ($)"].sum()
                    st.metric("Total Withdrawals", f"${sum_withdrawals:,.2f}")
                with col_met2:
                    sum_deposits = df["Deposit / Income ($)"].sum()
                    st.metric("Total Deposits", f"${sum_deposits:,.2f}")
                with col_met3:
                    sum_gst = df["GST ($)"].sum()
                    st.metric("Total GST Paid", f"${sum_gst:,.2f}")
                with col_met4:
                    sum_itc = df["Claimed ITC ($)"].sum()
                    st.metric("Total ITCs Claimed", f"${sum_itc:,.2f}")
                
                # Show net net summary info below
                st.markdown(f"**Net Amount:** &nbsp; **`${total_sum:,.2f}`** &nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp; **Line Count:** &nbsp; **`${tx_count} transactions`**")
                st.write("")
                col_ex1, col_ex2 = st.columns(2)
                
                # Prepare totals for exports
                total_withdrawal = df["Withdrawal / Expense ($)"].sum()
                total_deposit = df["Deposit / Income ($)"].sum()
                total_gst = df["GST ($)"].sum()
                total_itc = df["Claimed ITC ($)"].sum()
                
                with col_ex1:
                    # Prepare spreadsheet data (drop select and raw columns)
                    export_df = df[["TxID", "Account", "Date", "Original Memo", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)", "Category", "GST ($)", "Claimed ITC ($)"]]
                    
                    # Create a copy and append TOTAL and NET BALANCE rows for Excel
                    excel_df = export_df.copy()
                    total_row_excel = {
                        "TxID": "TOTAL",
                        "Account": "",
                        "Date": "",
                        "Original Memo": "",
                        "Merchant": "",
                        "Withdrawal / Expense ($)": total_withdrawal if total_withdrawal > 0 else None,
                        "Deposit / Income ($)": total_deposit if total_deposit > 0 else None,
                        "Category": "",
                        "GST ($)": total_gst,
                        "Claimed ITC ($)": total_itc
                    }
                    net_balance = total_deposit - total_withdrawal
                    net_row_excel = {
                        "TxID": "NET BALANCE",
                        "Account": "",
                        "Date": "",
                        "Original Memo": "",
                        "Merchant": "",
                        "Withdrawal / Expense ($)": None,
                        "Deposit / Income ($)": net_balance,
                        "Category": "",
                        "GST ($)": None,
                        "Claimed ITC ($)": None
                    }
                    excel_df = pd.concat([excel_df, pd.DataFrame([total_row_excel, net_row_excel])], ignore_index=True)
                    
                    from services.export_service import generate_excel_report
                    excel_data = generate_excel_report(excel_df, sheet_name="General Ledger")
                    st.download_button(
                        label="📥 Export Ledger to Excel (.xlsx)",
                        data=excel_data,
                        file_name=f"{client.business_name.lower().replace(' ', '_')}_ledger.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                with col_ex2:
                    from services.export_service import generate_pdf_report
                    headers_pdf = ["ID", "Account", "Date", "Memo", "Merchant", "Withdrawal ($)", "Deposit ($)", "Category", "GST ($)", "ITC ($)"]
                    pdf_rows = []
                    # Handle None values and format floats nicely for PDF
                    for _, row in export_df.iterrows():
                        pdf_rows.append([
                            str(row["TxID"]),
                            str(row["Account"]),
                            str(row["Date"]),
                            str(row["Original Memo"]),
                            str(row["Merchant"]),
                            f"${abs(row['Withdrawal / Expense ($)']):,.2f}" if pd.notna(row["Withdrawal / Expense ($)"]) else "",
                            f"${row['Deposit / Income ($)']:,.2f}" if pd.notna(row["Deposit / Income ($)"]) else "",
                            str(row["Category"]),
                            f"${row['GST ($)']:,.2f}",
                            f"${row['Claimed ITC ($)']:,.2f}"
                        ])
                        
                    # Append TOTAL row to PDF
                    pdf_rows.append([
                        "TOTAL",
                        "",
                        "",
                        "",
                        "",
                        f"${total_withdrawal:,.2f}" if total_withdrawal > 0 else "",
                        f"${total_deposit:,.2f}" if total_deposit > 0 else "",
                        "",
                        f"${total_gst:,.2f}",
                        f"${total_itc:,.2f}"
                    ])
                    
                    net_balance = total_deposit - total_withdrawal
                    pdf_rows.append([
                        "NET BALANCE",
                        "",
                        "",
                        "",
                        "",
                        "",
                        f"${net_balance:,.2f}" if net_balance >= 0 else f"-${abs(net_balance):,.2f}",
                        "",
                        "",
                        ""
                    ])
                    
                    pdf_data = generate_pdf_report(
                        title=f"General Ledger: {client.business_name} (Filter: {selected_filter})",
                        headers=headers_pdf,
                        rows=pdf_rows,
                        is_landscape=True
                    )
                    st.download_button(
                        label="📄 Export Ledger to PDF (.pdf)",
                        data=pdf_data,
                        file_name=f"{client.business_name.lower().replace(' ', '_')}_ledger.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                
                # Google Sheets Export Expander
                import os
                st.write("")
                with st.expander("🟢 Export Directly to Google Sheets"):
                    share_email = st.text_input("Your Google Email (to share the sheet with)", placeholder="your.name@gmail.com", key="gs_share_email")
                    master_sheet_name = st.text_input("Master Google Sheet Name", value="Maple Bookkeeping - Consolidated Ledgers", key="gs_master_sheet_gl")
                    
                    from services.google_sheets_service import google_credentials_configured
                    credentials_exists = google_credentials_configured()
                    if not credentials_exists:
                        st.info(
                            "🔑 **Google credentials file 'google_credentials.json' is not yet configured in the app root.**\n\n"
                            "To enable direct export to Google Sheets:\n"
                            "1. Go to the [Google Cloud Console](https://console.cloud.google.com/).\n"
                            "2. Create a new project, enable the **Google Sheets API** and **Google Drive API**.\n"
                            "3. Create a **Service Account** under credentials, generate a **JSON Key**, and download it.\n"
                            "4. Rename the downloaded file to `google_credentials.json` and place it in the root folder of this project (`C:\\Users\\admin\\.gemini\\antigravity\\scratch\\canadian_accounting_system`)."
                        )
                    else:
                        st.write("✅ API connection configured via `google_credentials.json`!")
                        if st.button("🚀 Push General Ledger to Google Sheets", key="btn_push_gs_gl"):
                            with st.spinner("Uploading to consolidated Google Sheet..."):
                                try:
                                    from services.google_sheets_service import upload_dataframe_to_google_sheets
                                    gs_url = upload_dataframe_to_google_sheets(
                                        df=excel_df,
                                        master_title=master_sheet_name,
                                        tab_title=f"{client.business_name} - Ledger",
                                        share_email=share_email if share_email else None
                                    )
                                    st.success("🎉 Successfully pushed to Google Sheet!")
                                    st.markdown(f"👉 **[Click here to open Consolidated Google Sheet]({gs_url})**")
                                except Exception as e:
                                    st.error(f"Failed to export to Google Sheets: {e}")
                st.write("")
                
            # Select / Deselect all button panel
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                if st.button("☑️ Check All Shown", use_container_width=True, key="btn_check_all_shown"):
                    st.session_state["ledger_select_all"] = True
                    st.rerun()
            with col_sel2:
                if st.button("⬜ Uncheck All Shown", use_container_width=True, key="btn_uncheck_all_shown"):
                    st.session_state["ledger_select_all"] = False
                    st.rerun()
            st.write("")
            
            edited_df = st.data_editor(
                df[["Select", "TxID", "Account", "Date", "Original Memo", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)", "Category", "GST ($)", "Claimed ITC ($)"]],
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", default=False),
                    "TxID": st.column_config.NumberColumn("ID", disabled=True),
                    "Account": st.column_config.TextColumn("Account", disabled=True),
                    "Date": st.column_config.TextColumn("Date", disabled=True),
                    "Original Memo": st.column_config.TextColumn("Original Memo", disabled=True),
                    "Merchant": st.column_config.TextColumn("Merchant", disabled=True),
                    "Withdrawal / Expense ($)": st.column_config.NumberColumn("Withdrawal / Expense", format="$%.2f", disabled=True),
                    "Deposit / Income ($)": st.column_config.NumberColumn("Deposit / Income", format="$%.2f", disabled=True),
                    "GST ($)": st.column_config.NumberColumn("GST Paid", format="$%.2f", disabled=False),
                    "Claimed ITC ($)": st.column_config.NumberColumn("ITC Claimed", format="$%.2f", disabled=False),
                    "Category": st.column_config.SelectboxColumn(
                        "Category",
                        help="Select standard chart of accounts category",
                        options=VALID_CATEGORIES,
                        required=True
                    )
                },
                disabled=["TxID", "Account", "Date", "Original Memo", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)"],
                num_rows="dynamic",
                use_container_width=True,
                key="ledger_data_editor"
            )
            
            # Bulk Operations Panel
            st.write("")
            with st.expander("⚡ Bulk Edit Checked Transactions", expanded=True):
                st.info("Check the **Select** box next to any transactions in the table above, then choose values below to bulk update them.")
                col_b1, col_b2, col_b3 = st.columns(3)
                with col_b1:
                    bulk_cat = st.selectbox("Set Category to...", ["No Change"] + VALID_CATEGORIES, key="bulk_cat_select")
                with col_b2:
                    bulk_gst = st.selectbox("Set GST Treatment to...", ["No Change", "Standard", "Exempt / Zero-Rated"], key="bulk_gst_select")
                with col_b3:
                    st.write("")
                    apply_bulk = st.button("⚡ Apply Bulk Update", type="primary", use_container_width=True)
                    
                if apply_bulk:
                    checked_rows = edited_df[edited_df["Select"] == True]
                    if checked_rows.empty:
                        st.warning("No transactions selected. Please check the 'Select' box next to transactions first.")
                    else:
                        from services.ledger_service import post_transaction_to_gl
                        from core.models import Client
                        client = db.query(Client).filter(Client.id == client_id).first()
                        
                        updated_count = 0
                        for _, row in checked_rows.iterrows():
                            tx_id = int(row["TxID"])
                            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
                            if tx:
                                modified = False
                                if bulk_cat != "No Change":
                                    tx.category = bulk_cat
                                    modified = True
                                
                                if bulk_gst != "No Change":
                                    if bulk_gst == "Exempt / Zero-Rated":
                                        tx.gst_amount = 0.0
                                        tx.itc_amount = 0.0
                                        modified = True
                                    elif bulk_gst == "Standard":
                                        # Recalculate standard 5% included GST
                                        amount = abs(tx.amount)
                                        gst_rate = 0.05
                                        gst_val = round(amount * (gst_rate / (1.0 + gst_rate)), 2)
                                        itc_val = gst_val
                                        
                                        cat_lower = (tx.category or "").lower()
                                        if "meals" in cat_lower or "entertainment" in cat_lower or "food" in cat_lower:
                                            itc_val = round(gst_val * 0.50, 2)
                                        elif "vehicle" in cat_lower or "fuel" in cat_lower or "gas" in cat_lower or "auto" in cat_lower:
                                            factor = (client.business_use_pct or 100.0) / 100.0
                                            itc_val = round(gst_val * factor, 2)
                                            
                                        tx.gst_amount = gst_val
                                        tx.itc_amount = itc_val
                                        modified = True
                                
                                if modified:
                                    db.add(tx)
                                    db.commit()
                                    post_transaction_to_gl(db, tx)
                                    updated_count += 1
                                    
                        if updated_count > 0:
                            st.session_state["ledger_select_all"] = False
                            st.success(f"Successfully bulk updated {updated_count} transactions!")
                            st.rerun()
            
            # Catch row deletions
            editor_state = st.session_state.get("ledger_data_editor", {})
            if editor_state and "deleted_rows" in editor_state and editor_state["deleted_rows"]:
                deleted_indices = editor_state["deleted_rows"]
                from core.models import JournalEntry, JournalLine
                with st.spinner("Deleting selected transaction(s) and re-balancing ledger..."):
                    for idx in deleted_indices:
                        tx_id = int(df.iloc[idx]["TxID"])
                        tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
                        if tx:
                            je = db.query(JournalEntry).filter(JournalEntry.transaction_id == tx.id).first()
                            if je:
                                db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).delete(synchronize_session=False)
                                db.delete(je)
                            db.delete(tx)
                    db.commit()
                st.toast("Deleted transaction(s) successfully!", icon="🗑️")
                st.rerun()
                
            # Catch category & GST/ITC edits
            for index, row in edited_df.iterrows():
                if index >= len(df):
                    continue
                tx_id = int(row["TxID"])
                
                # 1. Catch category changes
                old_cat = df.iloc[index]["Category"]
                new_cat = row["Category"]
                if old_cat != new_cat:
                    with st.spinner(f"Re-posting transaction {tx_id} to GL as {new_cat}..."):
                        update_transaction_category(db, tx_id, new_cat)
                    st.toast(f"Transaction reclassified to {new_cat}!", icon="✅")
                    st.rerun()
                    
                # 2. Catch manual GST/ITC value edits
                old_gst = float(df.iloc[index]["GST ($)"])
                new_gst = float(row["GST ($)"])
                old_itc = float(df.iloc[index]["Claimed ITC ($)"])
                new_itc = float(row["Claimed ITC ($)"])
                
                if old_gst != new_gst or old_itc != new_itc:
                    with st.spinner(f"Updating transaction {tx_id} manual GST/ITC settings..."):
                        update_transaction_gst_manual(db, tx_id, new_gst, new_itc)
                    st.toast(f"Transaction tax values updated manually!", icon="✅")
                    st.rerun()

    # ----------------------------------------------------
    # TAB 2: Bank Account Reconciliation & Rule Management
    # ----------------------------------------------------
    with tab_recon:
        bank_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
        if not bank_accounts:
            st.warning("Please link a bank account to this client under Client Management first.")
        elif not txs:
            st.info("No transaction records found in the ledger.")
        else:
            st.markdown("### Bank Account Reconciliation Tool")
            
            # Select bank account to reconcile
            bank_options = {f"{b.account_name} (*{b.account_number})": b for b in bank_accounts}
            selected_bank_lbl = st.selectbox("Select Account", list(bank_options.keys()))
            bank = bank_options[selected_bank_lbl]
            
            # Format account label with type for clear identification
            recon_type_lbl = "Bank Checking" if bank.account_type.lower() == "bank" else "Credit Card"
            recon_bank_display = f"{bank.account_name} ({recon_type_lbl})"
            
            # Filter transactions for this specific bank account
            bank_txs = [t for t in txs if t.account_id == bank.id]
            
            # Calculate running balances
            running_data = []
            current_bal = bank.opening_balance
            
            for t in bank_txs:
                current_bal += t.amount
                running_data.append({
                    "ID": t.id,
                    "Account": recon_bank_display,
                    "Date": t.date.strftime("%Y-%m-%d"),
                    "Original Description": t.original_description,
                    "Merchant": t.cleaned_description,
                    "Withdrawal / Expense ($)": abs(t.amount) if t.amount < 0 else None,
                    "Deposit / Income ($)": t.amount if t.amount > 0 else None,
                    "Category": t.category or "Suspense",
                    "Running Balance ($)": current_bal
                })
                
            df_recon = pd.DataFrame(running_data)
            
            # Reconciliation summary metrics cards
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric("Bank Starting Balance", f"${bank.opening_balance:,.2f}")
            with col_m2:
                st.metric("Ledger Ending Balance", f"${current_bal:,.2f}")
            with col_m3:
                statement_ending_input = st.number_input(
                    "Statement Ending Balance", 
                    value=float(current_bal), 
                    format="%.2f",
                    help="Enter the Ending Balance printed on your paper/PDF bank statement to reconcile."
                )
                
            discrepancy = current_bal - statement_ending_input
            if abs(discrepancy) <= 0.01:
                st.success("✅ **Reconciliation Status: Fully Balanced!** Ledger matches your bank statement ending balance.")
            else:
                st.error(f"⚠️ **Reconciliation Status: Discrepancy of ${abs(discrepancy):,.2f}!**\n"
                         f"Please compare the running balances table below line-by-line with your statement to locate missing or duplicate rows.")
                
            # Export options
            export_recon_df = df_recon[["ID", "Account", "Date", "Original Description", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)", "Category", "Running Balance ($)"]]
            from services.export_service import generate_excel_report
            excel_recon = generate_excel_report(export_recon_df, sheet_name="Reconciliation Ledger")
            
            from services.export_service import generate_pdf_report
            headers_recon = ["ID", "Account", "Date", "Original Description", "Merchant", "Withdrawal ($)", "Deposit ($)", "Category", "Running Balance ($)"]
            pdf_recon_rows = []
            for _, row in export_recon_df.iterrows():
                pdf_recon_rows.append([
                    str(row["ID"]),
                    str(row["Account"]),
                    str(row["Date"]),
                    str(row["Original Description"]),
                    str(row["Merchant"]),
                    f"${abs(row['Withdrawal / Expense ($)']):,.2f}" if pd.notna(row["Withdrawal / Expense ($)"]) else "",
                    f"${row['Deposit / Income ($)']:,.2f}" if pd.notna(row["Deposit / Income ($)"]) else "",
                    str(row["Category"]),
                    f"${row['Running Balance ($)']:,.2f}" if pd.notna(row["Running Balance ($)"]) else ""
                ])
            pdf_recon = generate_pdf_report(
                title=f"Reconciliation & Running Balance: {client.business_name} ({recon_bank_display})",
                headers=headers_recon,
                rows=pdf_recon_rows,
                is_landscape=True
            )
            
            col_ex_rec1, col_ex_rec2 = st.columns(2)
            with col_ex_rec1:
                st.download_button(
                    label="📥 Export Running Ledger to Excel (.xlsx)",
                    data=excel_recon,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_{bank.account_name.lower().replace(' ', '_')}_reconciliation.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_btn_recon_excel"
                )
            with col_ex_rec2:
                st.download_button(
                    label="📄 Export Running Ledger to PDF (.pdf)",
                    data=pdf_recon,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_{bank.account_name.lower().replace(' ', '_')}_reconciliation.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_btn_recon_pdf"
                )
            
            # Google Sheets Reconciliation Export Expander
            import os
            st.write("")
            with st.expander("🟢 Export Running Ledger to Google Sheets"):
                share_email_recon = st.text_input("Your Google Email (to share the sheet with)", placeholder="your.name@gmail.com", key="gs_share_email_recon")
                master_sheet_name_recon = st.text_input("Master Google Sheet Name", value="Maple Bookkeeping - Consolidated Ledgers", key="gs_master_sheet_recon")
                
                from services.google_sheets_service import google_credentials_configured
                credentials_exists = google_credentials_configured()
                if not credentials_exists:
                    st.info(
                        "🔑 **Google credentials file 'google_credentials.json' is not yet configured in the app root.**\n\n"
                        "To enable direct export to Google Sheets, place your Service Account key file named `google_credentials.json` in the root folder of this project."
                    )
                else:
                    st.write("✅ API connection configured via `google_credentials.json`!")
                    if st.button("🚀 Push Running Ledger to Google Sheets", key="btn_push_gs_recon"):
                        with st.spinner("Uploading to consolidated Google Sheet..."):
                            try:
                                from services.google_sheets_service import upload_dataframe_to_google_sheets
                                gs_url = upload_dataframe_to_google_sheets(
                                    df=export_recon_df,
                                    master_title=master_sheet_name_recon,
                                    tab_title=f"{bank.account_name} - Running",
                                    share_email=share_email_recon if share_email_recon else None
                                )
                                st.success("🎉 Successfully pushed to Google Sheet!")
                                st.markdown(f"👉 **[Click here to open Consolidated Google Sheet]({gs_url})**")
                            except Exception as e:
                                st.error(f"Failed to export to Google Sheets: {e}")
            st.write("")
            
            st.markdown("#### Running Balance Ledger")
            edited_recon_df = st.data_editor(
                df_recon[["ID", "Account", "Date", "Original Description", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)", "Category", "Running Balance ($)"]],
                column_config={
                    "ID": st.column_config.NumberColumn("ID", disabled=True),
                    "Account": st.column_config.TextColumn("Account", disabled=True),
                    "Date": st.column_config.TextColumn("Date", disabled=True),
                    "Original Description": st.column_config.TextColumn("Original Description", disabled=True),
                    "Merchant": st.column_config.TextColumn("Merchant", disabled=True),
                    "Withdrawal / Expense ($)": st.column_config.NumberColumn("Withdrawal / Expense", format="$%.2f", disabled=True),
                    "Deposit / Income ($)": st.column_config.NumberColumn("Deposit / Income", format="$%.2f", disabled=True),
                    "Running Balance ($)": st.column_config.NumberColumn("Running Balance", format="$%.2f", disabled=True),
                    "Category": st.column_config.SelectboxColumn(
                        "Category Mapped",
                        help="Select standard chart of accounts category",
                        options=VALID_CATEGORIES,
                        required=True
                    )
                },
                disabled=["ID", "Account", "Date", "Original Description", "Merchant", "Withdrawal / Expense ($)", "Deposit / Income ($)", "Running Balance ($)"],
                use_container_width=True,
                key="recon_data_editor"
            )
            
            # Detect category changes and rebuild ledger balances
            for index, row in edited_recon_df.iterrows():
                tx_id = int(row["ID"])
                old_cat = df_recon.iloc[index]["Category"]
                new_cat = row["Category"]
                
                if old_cat != new_cat:
                    with st.spinner(f"Re-posting transaction {tx_id} to GL as {new_cat}..."):
                        update_transaction_category(db, tx_id, new_cat)
                    st.toast(f"Transaction reclassified to {new_cat}!", icon="✅")
                    st.rerun()
            
            # Rule Management & AI Section combined under bank reconciliation
            st.write("")
            st.markdown("---")
            st.markdown("### ⚙️ Rule Management & AI Classifier")
            
            # AI and Bulk triggers
            protect_manual = st.checkbox("🔒 Protect manual classifications (do not overwrite already categorized transactions)", value=True, key="protect_manual_check")
            
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                ai_trigger = st.button("⚡ Run AI Auto-Categorize", type="primary", use_container_width=True, 
                                       help="Applies local rules first, then queries Gemini AI to categorize all Suspense transactions.")
            with col_t2:
                reapply_trigger = st.button("🔄 Re-Apply Rules to All", type="secondary", use_container_width=True,
                                            help="Re-runs keyword rule matching on all transactions and updates their GST/ITC values.")
                
            # Process triggers
            if ai_trigger:
                suspense_txs = db.query(Transaction).filter(
                    Transaction.client_id == client_id,
                    (Transaction.category == None) | (Transaction.category.in_(["Suspense Expense", "Suspense Revenue"]))
                ).all()
                
                if not suspense_txs:
                    st.info("General Ledger contains no suspense items needing classification.")
                else:
                    progress_bar = st.progress(0.0)
                    status_text = st.empty()
                    
                    classified = 0
                    for idx, tx in enumerate(suspense_txs):
                        status_text.text(f"Analyzing transaction {idx+1}/{len(suspense_txs)}: {tx.cleaned_description}...")
                        
                        # 1. Match local rules first
                        rule = match_local_rules(db, client_id, tx.cleaned_description, tx.original_description)
                        if rule:
                            update_transaction_category(db, tx.id, rule.category)
                        else:
                            # 2. Call Gemini AI
                            ai_res = suggest_merchant_category(tx.cleaned_description)
                            category = ai_res.get("category", "Suspense Expense")
                            update_transaction_category(db, tx.id, category)
                            
                        classified += 1
                        progress_bar.progress((idx + 1) / len(suspense_txs))
                        
                    status_text.empty()
                    progress_bar.empty()
                    st.success(f"Successfully auto-categorized {classified} ledger lines using Rules & Gemini AI!")
                    st.rerun()

            if reapply_trigger:
                all_txs = db.query(Transaction).filter(Transaction.client_id == client_id).all()
                if not all_txs:
                    st.info("General Ledger contains no transactions.")
                else:
                    progress_bar = st.progress(0.0)
                    status_text = st.empty()
                    
                    updated = 0
                    for idx, tx in enumerate(all_txs):
                        status_text.text(f"Re-applying rules to transaction {idx+1}/{len(all_txs)}: {tx.cleaned_description}...")
                        
                        # Skip if protection is on and transaction is already categorized
                        is_suspense = not tx.category or tx.category in ["Suspense Expense", "Suspense Revenue"]
                        if protect_manual and not is_suspense:
                            continue
                            
                        rule = match_local_rules(db, client_id, tx.cleaned_description, tx.original_description)
                        if rule:
                            update_transaction_category(db, tx.id, rule.category)
                            updated += 1
                        progress_bar.progress((idx + 1) / len(all_txs))
                        
                    status_text.empty()
                    progress_bar.empty()
                    st.success(f"Successfully re-applied rules! Updated {updated} transactions.")
                    st.rerun()
                    
            st.write("")
            st.markdown("#### ⚙️ Rule Configurator")
            
            col_r1, col_r2 = st.columns(2)
            
            with col_r1:
                st.write("**Create New Keyword Rule**")
                rule_kw = st.text_input("If Merchant Name contains...", placeholder="e.g. HUSKY, STARBUCKS, CRA")
                rule_cat = st.selectbox("Assign Category", VALID_CATEGORIES, key="rule_cat_select")
                
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    rule_gst = st.selectbox("GST Treatment", ["Standard", "Exempt", "Zero-Rated"], key="rule_gst_select")
                with col_g2:
                    st.write("")
                    rule_itc = st.checkbox("ITC Eligible", value=True, key="rule_itc_check")
                    
                rule_pct = st.slider("Business Use %", min_value=0.0, max_value=100.0, value=100.0, step=5.0, key="rule_pct_slider")
                
                if st.button("Save Matching Rule", type="secondary"):
                    if not rule_kw:
                        st.error("Please enter a match keyword.")
                    else:
                        rule = create_category_rule(
                            db, client_id, rule_kw, rule_cat, 
                            gst_treatment=rule_gst, itc_eligible=rule_itc, business_pct=rule_pct
                        )
                        
                        # Auto-apply to existing SUSPENSE transactions only
                        suspense_txs = db.query(Transaction).filter(
                            Transaction.client_id == client_id,
                            (Transaction.category == None) | (Transaction.category.in_(["Suspense Expense", "Suspense Revenue"]))
                        ).all()
                        
                        applied_count = 0
                        kw_upper = rule.keyword.upper()
                        for tx in suspense_txs:
                            merchant_upper = tx.cleaned_description.upper() if tx.cleaned_description else ""
                            orig_upper = tx.original_description.upper() if tx.original_description else ""
                            if kw_upper in merchant_upper or kw_upper in orig_upper:
                                update_transaction_category(db, tx.id, rule.category)
                                applied_count += 1
                                
                        if applied_count > 0:
                            st.success(f"Rule saved and auto-applied to {applied_count} matching suspense transactions!")
                        else:
                            st.success(f"Rule saved: Map '{rule_kw.upper()}' to '{rule_cat}'!")
                        st.rerun()
                        
                st.write("---")
                st.write("**📤 Batch Import Rules (CSV or Excel)**")
                uploaded_rules_file = st.file_uploader(
                    "Upload Rules Spreadsheet", 
                    type=["csv", "xlsx"], 
                    key="rules_file_uploader",
                    help="Upload a spreadsheet containing 'Keyword' and 'Category' columns to import rules in batch."
                )
                
                if uploaded_rules_file is not None:
                    st.write("")
                    import_btn = st.button("📥 Import Rules from File", type="primary", use_container_width=True)
                    
                    if import_btn:
                        try:
                            if uploaded_rules_file.name.endswith(".csv"):
                                df_rules = pd.read_csv(uploaded_rules_file)
                            else:
                                df_rules = pd.read_excel(uploaded_rules_file)
                                
                            kw_col = None
                            cat_col = None
                            for col in df_rules.columns:
                                col_lower = str(col).lower().strip()
                                if "keyword" in col_lower or "match" in col_lower:
                                    kw_col = col
                                elif "category" in col_lower or "coa" in col_lower or "account" in col_lower:
                                    cat_col = col
                                    
                            if kw_col is None or cat_col is None:
                                st.error("Uploaded file must contain 'Keyword' and 'Category' columns.")
                            else:
                                # Fetch existing SUSPENSE transactions to auto-apply imported rules
                                suspense_txs = db.query(Transaction).filter(
                                    Transaction.client_id == client_id,
                                    (Transaction.category == None) | (Transaction.category.in_(["Suspense Expense", "Suspense Revenue"]))
                                ).all()
                                
                                imported = 0
                                for _, row_item in df_rules.iterrows():
                                    kw_val = str(row_item[kw_col]).strip()
                                    cat_val = str(row_item[cat_col]).strip()
                                    
                                    # Fuzzy match category names
                                    cat_clean = cat_val.lower().strip()
                                    matched_cat = None
                                    
                                    # 1. Direct lowercase match
                                    for vc in VALID_CATEGORIES:
                                        if vc.lower().strip() == cat_clean:
                                            matched_cat = vc
                                            break
                                            
                                    # 2. Fuzzy mapping dictionary
                                    if not matched_cat:
                                        fuzzy_map = {
                                            "bank charges": "Bank Fees",
                                            "bank fee": "Bank Fees",
                                            "bank fees": "Bank Fees",
                                            "fuel": "Auto Fuel",
                                            "gas": "Auto Fuel",
                                            "auto fuel": "Auto Fuel",
                                            "income": "Sales Revenue",
                                            "trade sales": "Sales Revenue",
                                            "sales": "Sales Revenue",
                                            "revenue": "Sales Revenue",
                                            "meals": "Meals & Entertainment",
                                            "meals & entertainment": "Meals & Entertainment",
                                            "meals/entertainment": "Meals & Entertainment",
                                            "office expense": "Office Supplies",
                                            "office supplies": "Office Supplies",
                                            "office exp usa": "Office Supplies",
                                            "office": "Office Supplies",
                                            "advertising": "Advertising",
                                            "ads": "Advertising",
                                            "rent": "Rent",
                                            "lease 5%": "Rent",
                                            "insurance": "Insurance",
                                            "auto insurance": "Insurance",
                                            "subcontract 5%": "Subcontractors",
                                            "subcontractors": "Subcontractors",
                                            "license fees": "Taxes & Licenses",
                                            "licenses": "Taxes & Licenses",
                                            "taxes & licenses": "Taxes & Licenses",
                                            "repair": "Repairs & Maintenance",
                                            "repair 5%": "Repairs & Maintenance"
                                        }
                                        matched_cat = fuzzy_map.get(cat_clean, None)
                                        
                                     # 3. Fallback default
                                    if not matched_cat:
                                        matched_cat = "Suspense Expense"
                                        
                                    if kw_val and matched_cat:
                                        rule = create_category_rule(db, client_id, kw_val, matched_cat)
                                        imported += 1
                                        
                                        # Auto-apply to matched suspense transactions in this batch run
                                        kw_upper = rule.keyword.upper()
                                        for tx in suspense_txs:
                                            # Skip if already updated during this session to avoid double DB hit
                                            if tx.category == rule.category:
                                                continue
                                            merchant_upper = tx.cleaned_description.upper() if tx.cleaned_description else ""
                                            orig_upper = tx.original_description.upper() if tx.original_description else ""
                                            if kw_upper in merchant_upper or kw_upper in orig_upper:
                                                update_transaction_category(db, tx.id, rule.category)
                                                tx.category = rule.category # locally cache status to skip in next rule loops
                                        
                                st.success(f"Successfully imported {imported} rules and auto-classified matching suspense items!")
                                st.rerun()
                        except Exception as ex:
                            st.error(f"Failed to parse rules file: {ex}")
                            
                st.write("---")
                st.write("**📋 Clone Rules from Another Client**")
                other_clients = [c for c in clients if c.id != client_id]
                if not other_clients:
                    st.info("No other client profiles exist to clone rules from.")
                else:
                    other_client_options = {c.business_name: c.id for c in other_clients}
                    src_client_name = st.selectbox("Select Client to Copy From", list(other_client_options.keys()), key="clone_rules_src_select")
                    src_client_id = other_client_options[src_client_name]
                    if st.button("📋 Copy Rules to Current Client", type="secondary", use_container_width=True):
                        # Copy rules from src_client_id to client_id
                        src_rules = db.query(CategoryRule).filter(CategoryRule.client_id == src_client_id).all()
                        copied_count = 0
                        for r in src_rules:
                            # Avoid duplicates
                            existing = db.query(CategoryRule).filter(
                                CategoryRule.client_id == client_id,
                                CategoryRule.keyword == r.keyword
                            ).first()
                            if not existing:
                                new_rule = CategoryRule(
                                    client_id=client_id,
                                    keyword=r.keyword,
                                    category=r.category,
                                    gst_treatment=r.gst_treatment,
                                    itc_eligible=r.itc_eligible,
                                    business_pct=r.business_pct,
                                    confidence=r.confidence
                                )
                                db.add(new_rule)
                                copied_count += 1
                        db.commit()
                        st.success(f"Successfully copied {copied_count} rules from {src_client_name}!")
                        st.rerun()
                            
            with col_r2:
                st.write("**Existing Client Keyword Rules**")
                st.info("Double-click any cell below to edit the category or GST parameters. Settings are committed instantly.")
                rules = get_client_rules(db, client_id)
                if not rules:
                    st.info("No keyword rules defined for this client yet.")
                else:
                    rules_data = []
                    for r in rules:
                        rules_data.append({
                            "RuleID": r.id,
                            "Keyword Match": r.keyword,
                            "Map Category": r.category,
                            "GST Treatment": r.gst_treatment,
                            "ITC Eligible": r.itc_eligible,
                            "Business Use %": r.business_pct
                        })
                    df_rules_grid = pd.DataFrame(rules_data)
                    
                    # 📥 Export to CSV download button
                    csv_content = df_rules_grid.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Rules CSV",
                        data=csv_content,
                        file_name=f"{client.business_name.lower().replace(' ', '_')}_rules.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key="download_rules_csv_btn"
                    )
                    st.write("")
                    
                    edited_rules_df = st.data_editor(
                        df_rules_grid,
                        column_config={
                            "RuleID": st.column_config.NumberColumn("ID", disabled=True),
                            "Keyword Match": st.column_config.TextColumn("Keyword Match", disabled=True),
                            "Map Category": st.column_config.SelectboxColumn(
                                "Map Category",
                                options=VALID_CATEGORIES,
                                required=True
                            ),
                            "GST Treatment": st.column_config.SelectboxColumn(
                                "GST Treatment",
                                options=["Standard", "Exempt", "Zero-Rated"],
                                required=True
                            ),
                            "ITC Eligible": st.column_config.CheckboxColumn("ITC Eligible"),
                            "Business Use %": st.column_config.NumberColumn("Business Use %", min_value=0.0, max_value=100.0, format="%.1f%%")
                        },
                        disabled=["RuleID", "Keyword Match"],
                        num_rows="dynamic",
                        use_container_width=True,
                        key="rules_grid_data_editor"
                    )
                    
                    # Catch rule deletions
                    rules_editor_state = st.session_state.get("rules_grid_data_editor", {})
                    if rules_editor_state and "deleted_rows" in rules_editor_state and rules_editor_state["deleted_rows"]:
                        deleted_indices = rules_editor_state["deleted_rows"]
                        with st.spinner("Deleting selected keyword rule(s)..."):
                            for idx in deleted_indices:
                                r_id = int(df_rules_grid.iloc[idx]["RuleID"])
                                db_rule = db.query(CategoryRule).filter(CategoryRule.id == r_id).first()
                                if db_rule:
                                    db.delete(db_rule)
                            db.commit()
                        st.toast("Deleted rule(s) successfully!", icon="🗑️")
                        st.rerun()
                    
                    for index, row in edited_rules_df.iterrows():
                        r_id = int(row["RuleID"])
                        orig = df_rules_grid.iloc[index]
                        
                        if (row["Map Category"] != orig["Map Category"] or 
                            row["GST Treatment"] != orig["GST Treatment"] or 
                            row["ITC Eligible"] != orig["ITC Eligible"] or 
                            row["Business Use %"] != orig["Business Use %"]):
                            
                            db_rule = db.query(CategoryRule).filter(CategoryRule.id == r_id).first()
                            if db_rule:
                                db_rule.category = row["Map Category"]
                                db_rule.gst_treatment = row["GST Treatment"]
                                db_rule.itc_eligible = row["ITC Eligible"]
                                db_rule.business_pct = float(row["Business Use %"])
                                db.commit()
                                st.toast(f"Updated rule '{db_rule.keyword}'!", icon="✅")
                                st.rerun()
                                 
                    # Explicit rule deletion panel
                    st.write("")
                    st.markdown("##### 🗑️ Delete Rule")
                    rule_opts = {r.keyword: r.id for r in rules}
                    col_del1, col_del2 = st.columns([3, 1])
                    with col_del1:
                        selected_del_kw = st.selectbox("Select keyword rule to delete", list(rule_opts.keys()), key="selectbox_delete_rule")
                    with col_del2:
                        st.write("")
                        if st.button("🗑️ Delete Rule", type="primary", use_container_width=True, key="btn_delete_rule"):
                            rule_id_to_del = rule_opts[selected_del_kw]
                            db_rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id_to_del).first()
                            if db_rule:
                                db.delete(db_rule)
                                db.commit()
                                st.toast(f"Deleted rule '{selected_del_kw}' successfully!", icon="🗑️")
                                st.rerun()
                                

    with tab_tx_cat:
        st.subheader("📂 Transactions Grouped by Category")
        
        if not txs:
            st.info("No transactions found.")
        else:
            # Group transactions
            by_category = {}
            for t in txs:
                cat = t.category or ("Suspense Revenue" if t.amount > 0 else "Suspense Expense")
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(t)
                
            cat_list = sorted(list(by_category.keys()))
            
            # Prepare export lists and grand totals trackers
            export_rows = []
            pdf_rows = []
            
            grand_total_withdrawal = 0.0
            grand_total_deposit = 0.0
            grand_total_gst = 0.0
            
            for cat in cat_list:
                cat_txs = by_category[cat]
                st.markdown(f"#### 📂 {cat}")
                
                cat_rows = []
                cat_total_withdrawal = 0.0
                cat_total_deposit = 0.0
                
                for t in cat_txs:
                    amt = abs(t.amount)
                    withdrawal_val = amt if t.amount < 0 else None
                    deposit_val = amt if t.amount > 0 else None
                    gst_val = t.gst_amount or 0.0
                    
                    if withdrawal_val is not None:
                        cat_total_withdrawal += withdrawal_val
                        grand_total_withdrawal += withdrawal_val
                    if deposit_val is not None:
                        cat_total_deposit += deposit_val
                        grand_total_deposit += deposit_val
                    grand_total_gst += gst_val
                        
                    acc_name = bank_names.get(t.account_id, "Unknown")
                    cat_rows.append({
                        "Date": t.date.strftime("%Y-%m-%d"),
                        "Account": acc_name,
                        "Merchant": t.cleaned_description,
                        "Withdrawal / Debit ($)": f"${withdrawal_val:,.2f}" if withdrawal_val is not None else "",
                        "Deposit / Credit ($)": f"${deposit_val:,.2f}" if deposit_val is not None else "",
                        "GST ($)": f"${t.gst_amount or 0.0:,.2f}"
                    })
                    
                    export_rows.append({
                        "Category": cat,
                        "Date": t.date.strftime("%Y-%m-%d"),
                        "Account": acc_name,
                        "Merchant": t.cleaned_description,
                        "Withdrawal / Debit": withdrawal_val,
                        "Deposit / Credit": deposit_val,
                        "GST": t.gst_amount or 0.0
                    })
                    pdf_rows.append([
                        cat,
                        t.date.strftime("%Y-%m-%d"),
                        acc_name,
                        t.cleaned_description,
                        f"${withdrawal_val:,.2f}" if withdrawal_val is not None else "",
                        f"${deposit_val:,.2f}" if deposit_val is not None else "",
                        f"${t.gst_amount or 0.0:,.2f}"
                    ])
                    
                # Add subtotal row to exports
                export_rows.append({
                    "Category": cat,
                    "Date": "SUBTOTAL",
                    "Account": "",
                    "Merchant": "",
                    "Withdrawal / Debit": cat_total_withdrawal if cat_total_withdrawal > 0 else 0.0,
                    "Deposit / Credit": cat_total_deposit if cat_total_deposit > 0 else 0.0,
                    "GST": ""
                })
                pdf_rows.append([
                    cat,
                    "SUBTOTAL",
                    "",
                    "",
                    f"${cat_total_withdrawal:,.2f}" if cat_total_withdrawal > 0 else "",
                    f"${cat_total_deposit:,.2f}" if cat_total_deposit > 0 else "",
                    ""
                ])
                
                st.table(pd.DataFrame(cat_rows))
                st.markdown(f"**Total Withdrawal:** &nbsp; **`${cat_total_withdrawal:,.2f}`** &nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp; **Total Deposit:** &nbsp; **`${cat_total_deposit:,.2f}`**")
                st.markdown("---")
                
            # Display Grand Totals on Screen
            st.markdown("### 🏆 Grand Totals (All Categories Combined)")
            grand_net = grand_total_deposit - grand_total_withdrawal
            col_gt1, col_gt2, col_gt3, col_gt4 = st.columns(4)
            with col_gt1:
                st.metric("Grand Total Withdrawals", f"${grand_total_withdrawal:,.2f}")
            with col_gt2:
                st.metric("Grand Total Deposits", f"${grand_total_deposit:,.2f}")
            with col_gt3:
                st.metric("Grand Net Balance", f"${grand_net:,.2f}")
            with col_gt4:
                st.metric("Grand Total GST", f"${grand_total_gst:,.2f}")
            st.markdown("---")
            
            # Append Grand Total and Grand Net Balance rows to exports
            export_rows.append({
                "Category": "GRAND TOTAL",
                "Date": "",
                "Account": "",
                "Merchant": "",
                "Withdrawal / Debit": grand_total_withdrawal if grand_total_withdrawal > 0 else 0.0,
                "Deposit / Credit": grand_total_deposit if grand_total_deposit > 0 else 0.0,
                "GST": grand_total_gst
            })
            export_rows.append({
                "Category": "GRAND NET BALANCE",
                "Date": "",
                "Account": "",
                "Merchant": "",
                "Withdrawal / Debit": 0.0,
                "Deposit / Credit": grand_net,
                "GST": 0.0
            })
            
            pdf_rows.append([
                "GRAND TOTAL",
                "",
                "",
                "",
                f"${grand_total_withdrawal:,.2f}" if grand_total_withdrawal > 0 else "",
                f"${grand_total_deposit:,.2f}" if grand_total_deposit > 0 else "",
                f"${grand_total_gst:,.2f}"
            ])
            pdf_rows.append([
                "GRAND NET BALANCE",
                "",
                "",
                "",
                "",
                f"${grand_net:,.2f}" if grand_net >= 0 else f"-${abs(grand_net):,.2f}",
                ""
            ])
                
            # Export controls
            st.write("")
            st.markdown("#### 📥 Export Grouped Report")
            col_ex_cat1, col_ex_cat2 = st.columns(2)
            with col_ex_cat1:
                from services.export_service import generate_excel_report
                excel_cat = generate_excel_report(pd.DataFrame(export_rows), sheet_name="By Category")
                st.download_button(
                    label="📥 Export to Excel (.xlsx)",
                    data=excel_cat,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_by_category.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_btn_cat_excel"
                )
            with col_ex_cat2:
                from services.export_service import generate_pdf_report
                pdf_headers = ["Category", "Date", "Account", "Merchant", "Withdrawal ($)", "Deposit ($)", "GST ($)"]
                pdf_cat = generate_pdf_report(
                    title=f"Transactions Grouped by Category: {client.business_name}",
                    headers=pdf_headers,
                    rows=pdf_rows,
                    is_landscape=False
                )
                st.download_button(
                    label="📄 Export to PDF (.pdf)",
                    data=pdf_cat,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_by_category.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_btn_cat_pdf"
                )
            
            # Google Sheets Category Export Expander
            import os
            st.write("")
            with st.expander("🟢 Export Grouped Report to Google Sheets"):
                share_email_cat = st.text_input("Your Google Email (to share the sheet with)", placeholder="your.name@gmail.com", key="gs_share_email_cat")
                master_sheet_name_cat = st.text_input("Master Google Sheet Name", value="Maple Bookkeeping - Consolidated Ledgers", key="gs_master_sheet_cat")
                
                from services.google_sheets_service import google_credentials_configured
                credentials_exists = google_credentials_configured()
                if not credentials_exists:
                    st.info(
                        "🔑 **Google credentials file 'google_credentials.json' is not yet configured in the app root.**\n\n"
                        "To enable direct export to Google Sheets, place your Service Account key file named `google_credentials.json` in the root folder of this project."
                    )
                else:
                    st.write("✅ API connection configured via `google_credentials.json`!")
                    if st.button("🚀 Push Grouped Report to Google Sheets", key="btn_push_gs_cat"):
                        with st.spinner("Uploading to consolidated Google Sheet..."):
                            try:
                                from services.google_sheets_service import upload_dataframe_to_google_sheets
                                gs_url = upload_dataframe_to_google_sheets(
                                    df=pd.DataFrame(export_rows),
                                    master_title=master_sheet_name_cat,
                                    tab_title=f"{client.business_name} - Category",
                                    share_email=share_email_cat if share_email_cat else None
                                )
                                st.success("🎉 Successfully pushed to Google Sheet!")
                                st.markdown(f"👉 **[Click here to open Consolidated Google Sheet]({gs_url})**")
                            except Exception as e:
                                st.error(f"Failed to export to Google Sheets: {e}")
            st.write("")

    st.write("")
    st.write("")
    with st.expander("⚠️ Danger Zone - Reset General Ledger"):
        st.markdown("**Reset client transaction history**")
        st.write("Wipes transaction history, double-entry journal entries, and audit logs. This action is irreversible.")
        
        # Account selector for deletion
        bank_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
        reset_options = ["Wipe ALL Accounts Combined"] + [f"Wipe {b.account_name} (*{b.account_number})" for b in bank_accounts]
        selected_reset_opt = st.selectbox("Select Target Account to Reset", reset_options, key="danger_zone_account_select")
        
        confirm_reset = st.checkbox(f"I understand this will delete all transactions and ledger balances for: {selected_reset_opt}", key="confirm_bulk_wipe_check")
        
        if st.button("🔥 Execute Reset and Wipe Transactions", type="primary", disabled=not confirm_reset, use_container_width=True):
            from core.models import JournalEntry, JournalLine
            
            if selected_reset_opt == "Wipe ALL Accounts Combined":
                # Wipe everything for this client
                db.query(JournalLine).filter(JournalLine.journal_entry_id.in_(
                    db.query(JournalEntry.id).filter(JournalEntry.client_id == client_id)
                )).delete(synchronize_session=False)
                db.query(JournalEntry).filter(JournalEntry.client_id == client_id).delete(synchronize_session=False)
                db.query(Transaction).filter(Transaction.client_id == client_id).delete(synchronize_session=False)
                db.commit()
                st.success("General Ledger successfully reset. All transactions deleted.")
            else:
                # Find selected bank account ID
                chosen_idx = reset_options.index(selected_reset_opt) - 1
                target_bank = bank_accounts[chosen_idx]
                
                # Delete lines first
                db.query(JournalLine).filter(JournalLine.journal_entry_id.in_(
                    db.query(JournalEntry.id).filter(JournalEntry.transaction_id.in_(
                        db.query(Transaction.id).filter(
                            Transaction.client_id == client_id,
                            Transaction.account_id == target_bank.id
                        )
                    ))
                )).delete(synchronize_session=False)
                
                # Delete entries
                db.query(JournalEntry).filter(JournalEntry.transaction_id.in_(
                    db.query(Transaction.id).filter(
                        Transaction.client_id == client_id,
                        Transaction.account_id == target_bank.id
                    )
                )).delete(synchronize_session=False)
                
                # Delete transactions
                db.query(Transaction).filter(
                    Transaction.client_id == client_id,
                    Transaction.account_id == target_bank.id
                ).delete(synchronize_session=False)
                
                db.commit()
                st.success(f"Successfully deleted all transactions for {target_bank.account_name}!")
                
            st.rerun()
