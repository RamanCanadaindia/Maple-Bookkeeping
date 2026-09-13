import streamlit as st
import pandas as pd
from datetime import datetime
from services.client_service import get_clients, get_client_by_id
from services.extractor_service import parse_csv_statement, parse_pdf_statement, parse_xlsx_statement
from services.duplicate_service import check_is_duplicate
from services.transfer_service import detect_internal_transfers
from services.audit_service import log_action
from core.models import Transaction, ClientBankAccount
from services.local_mapping_service import LocalMappingEngine, learn_mapping
from services.google_sheets_service import google_credentials_configured

def render_statement_import(db):
    """
    Renders the statement ingestion dashboard tab.
    """
    st.subheader("📥 Ingest Bank & Credit Card Statements")
    
    current_user = st.session_state.get("current_user")
    clients = get_clients(db, current_user)
    if not clients:
        st.warning("No client accounts are assigned to your profile.")
        return
        
    # Form Layout
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        client_options = {c.business_name: c.id for c in clients}
        
        from services.client_service import sync_global_active_client
        widget_key = "statement_client_select"
        on_change_cb = sync_global_active_client(widget_key, client_options)
        
        client_name = st.selectbox("Client Account", list(client_options.keys()), key=widget_key, on_change=on_change_cb)
        client_id = client_options[client_name]
        
        from services.client_service import verify_client_access
        if not verify_client_access(db, client_id, current_user):
            st.error("Access Denied: You do not have permissions to access this client's records.")
            return
            
        client = get_client_by_id(db, client_id)
        
    with col_c2:
        # Get linked bank accounts for this client
        accounts = client.bank_accounts
        if not accounts:
            st.error("No bank accounts linked to this client. Go to Client Management to link one first.")
            return
            
        acc_options = {f"{a.account_name} (*{a.account_number or 'N/A'})": a.id for a in accounts}
        acc_label = st.selectbox("Linked Bank Ledger", list(acc_options.keys()))
        account_id = acc_options[acc_label]
        
    # ── Import Method Tabs ────────────────────────────────────────────────
    file_tab, gsheet_tab = st.tabs(["📎 Upload File (PDF / CSV / Excel)", "🔗 Import from Google Sheets"])

    # ── Tab 1: File Upload ────────────────────────────────────────────────
    with file_tab:
        uploaded_file = st.file_uploader(
            "Drag & Drop Statement File (PDF, CSV, or Excel)",
            type=["pdf", "csv", "xlsx"],
            help="Supports PDF bank statements and CSV/Excel exports (including Google Sheets downloaded as Excel)."
        )

        with st.expander("ℹ️ CSV / Excel Import Formatting Guide"):
            st.markdown("""
            Ensure your file has headers the app can auto-detect.

            ### Required Columns:
            1. **Date** — any header containing `Date`.
            2. **Description** — any header containing `Description`, `Memo`, `Detail`, `Particulars`, or `Name`.
            3. **Amount** — either:
               - Single column named `Amount` or `Value` (negative = withdrawal, positive = deposit).
               - Two columns named `Debit` / `Withdrawal` and `Credit` / `Deposit`.

            ### Optional Columns:
            - **Balance** — running account balance.
            - **Category** — pre-assigned ledger category (honoured as-is on import).
            """)
            sample_df = pd.DataFrame([
                {"Date": "2026-07-21", "Description": "Rogers Wireless", "Amount": -112.50, "Category": "Telephone Expense", "Balance": 1450.20},
                {"Date": "2026-07-21", "Description": "Client Deposit",  "Amount": 2500.00, "Category": "Professional Fees",  "Balance": 3950.20},
            ])
            st.dataframe(sample_df, use_container_width=True, hide_index=True)

        if uploaded_file is not None:
            file_bytes = uploaded_file.read()
            file_type = uploaded_file.name.split(".")[-1].lower()

            st.write("")
            ingest_btn = st.button("🚀 Ingest & Extract Transactions", type="primary", use_container_width=True, key="file_ingest_btn")

            if ingest_btn:
                with st.spinner("Extracting transactional tables and applying cleaning logic..."):
                    try:
                        if file_type == "csv":
                            raw_txs = parse_csv_statement(file_bytes)
                        elif file_type == "xlsx":
                            raw_txs = parse_xlsx_statement(file_bytes)
                        else:
                            raw_txs = parse_pdf_statement(file_bytes)

                        if not raw_txs:
                            st.error("Failed to extract any transactions. Verify that the file contains digital text tables.")
                        else:
                            st.session_state["parsed_tx_batch"] = raw_txs
                            st.session_state["active_import_client_id"] = client_id
                            st.session_state["active_import_account_id"] = account_id
                            st.success(f"Successfully extracted {len(raw_txs)} transactions from file!")
                    except Exception as e:
                        st.error(f"Extraction Pipeline failed: {e}")

    # ── Tab 2: Google Sheets URL ──────────────────────────────────────────
    with gsheet_tab:
        if not google_credentials_configured():
            st.warning("Google Sheets is not configured. Add `[google_service_account]` to Streamlit secrets.")
        else:
            st.markdown("Paste the URL of your Google Sheet. The service account must have **Viewer** access to the spreadsheet.")
            sheet_url = st.text_input(
                "Google Sheets URL",
                placeholder="https://docs.google.com/spreadsheets/d/...",
                key="gsheet_import_url"
            )

            if sheet_url:
                load_btn = st.button("📋 Load Worksheets", key="gsheet_load_btn")
                if load_btn:
                    with st.spinner("Connecting to Google Sheets..."):
                        try:
                            import gspread
                            from services.google_sheets_service import _google_credentials
                            scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                                      "https://www.googleapis.com/auth/drive.readonly"]
                            creds = _google_credentials(scopes)
                            gc = gspread.authorize(creds)
                            sh = gc.open_by_url(sheet_url)
                            ws_names = [ws.title for ws in sh.worksheets()]
                            st.session_state["gsheet_ws_names"] = ws_names
                            st.session_state["gsheet_loaded_url"] = sheet_url
                        except Exception as e:
                            st.error(f"Could not open spreadsheet: {e}")

                if "gsheet_ws_names" in st.session_state and st.session_state.get("gsheet_loaded_url") == sheet_url:
                    ws_names = st.session_state["gsheet_ws_names"]
                    selected_ws = st.selectbox("Select Worksheet (Tab) to Import", ws_names, key="gsheet_ws_select")

                    st.info(f"📄 Will import transactions from the **{selected_ws}** tab. Columns expected: Date, Description, Amount, Category.")

                    gs_ingest_btn = st.button("🚀 Import from Google Sheets", type="primary", use_container_width=True, key="gsheet_ingest_btn")
                    if gs_ingest_btn:
                        with st.spinner(f"Reading '{selected_ws}' from Google Sheets..."):
                            try:
                                import gspread, io, csv as _csv
                                from services.google_sheets_service import _google_credentials
                                scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                                          "https://www.googleapis.com/auth/drive.readonly"]
                                creds = _google_credentials(scopes)
                                gc = gspread.authorize(creds)
                                sh = gc.open_by_url(sheet_url)
                                ws = sh.worksheet(selected_ws)
                                rows = ws.get_all_values()
                                if not rows:
                                    st.error("The selected worksheet is empty.")
                                else:
                                    buf = io.StringIO()
                                    _csv.writer(buf).writerows(rows)
                                    raw_txs = parse_csv_statement(buf.getvalue().encode("utf-8"))
                                    if not raw_txs:
                                        st.error("Could not detect transactions. Check that the sheet has Date, Description, and Amount columns.")
                                    else:
                                        st.session_state["parsed_tx_batch"] = raw_txs
                                        st.session_state["active_import_client_id"] = client_id
                                        st.session_state["active_import_account_id"] = account_id
                                        st.success(f"✅ Loaded {len(raw_txs)} transactions from **{selected_ws}**. Scroll down to review and post.")
                            except Exception as e:
                                st.error(f"Google Sheets import failed: {e}")
                    
    # Render Review spreadsheet if batch exists in state
    if "parsed_tx_batch" in st.session_state and st.session_state.get("active_import_client_id") == client_id:
        batch = st.session_state["parsed_tx_batch"]
        account_id = st.session_state["active_import_account_id"]
        
        st.write("")
        st.subheader("📋 Transaction Ingestion Review Panel")
        st.info("Desktop mapping uses this client's rules and confirmed history. Transaction text stays on this computer.")
        
        # Build bank map for internal transfer detection
        all_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
        bank_map = {a.id: a.account_name for a in all_accounts}
        
        # Apply transfer matcher on batch
        # Map account ID into batch objects
        for b in batch:
            b["account_id"] = account_id
            
        processed_batch = detect_internal_transfers(batch, bank_map)
        
        # Apply duplicate checks on batch
        mapper = LocalMappingEngine(db, client_id)
        mapping_results = mapper.categorize_many(processed_batch)
        review_data = []
        for idx, tx in enumerate(processed_batch):
            is_dup = check_is_duplicate(
                db=db,
                client_id=client_id,
                account_id=account_id,
                tx_date=tx["date"],
                amount=tx["amount"],
                cleaned_desc=tx["cleaned_description"]
            )
            
            mapping = mapping_results[idx]
            imported_category = (tx.get("category") or "").strip()
            # A category supplied by the file is treated as a user-provided value.
            suggested_category = imported_category or mapping.category
            confidence = 1.0 if imported_category else mapping.confidence
            needs_review = False if imported_category else mapping.review_required
            review_data.append({
                "Index": idx,
                "Date": tx["date"].strftime("%Y-%m-%d"),
                "Original Memo": tx["original_description"],
                "Merchant": tx["cleaned_description"],
                "Amount ($ CAD)": f"${tx['amount']:,.2f}",
                "Balance ($)": f"${tx['balance']:,.2f}",
                "Category": suggested_category,
                "Confidence": confidence,
                "Mapping Source": "imported" if imported_category else mapping.source,
                "Review Required": needs_review,
                "Duplicate?": "⚠️ Yes (Match Found)" if is_dup else "No",
                "Internal Transfer?": "🔄 Yes" if tx.get("is_transfer") else "No",
                "Skip Import": is_dup,  # Default to skipping if duplicate
                "is_transfer": tx.get("is_transfer", False),
                "transfer_linked_acc": tx.get("transfer_linked_acc", None),
                "debit": tx["debit"],
                "credit": tx["credit"],
                "amount_val": tx["amount"],
                "balance_val": tx["balance"]
            })
            
        df_review = pd.DataFrame(review_data)
        
        # Render clean editable dataframe review grid
        edited_df = st.data_editor(
            df_review[["Date", "Original Memo", "Merchant", "Amount ($ CAD)", "Balance ($)", "Category", "Confidence", "Mapping Source", "Review Required", "Duplicate?", "Internal Transfer?", "Skip Import"]],
            column_config={
                "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0, format="%.0f%%"),
                "Review Required": st.column_config.CheckboxColumn("Review?"),
            },
            use_container_width=True,
            num_rows="fixed",
            disabled=["Date", "Original Memo", "Amount ($ CAD)", "Balance ($)", "Confidence", "Mapping Source", "Duplicate?", "Internal Transfer?"]
        )
        
        st.write("")
        
        # Download options for CSV / Excel (capturing current state of the edited grid)
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_data = edited_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download as CSV",
                data=csv_data,
                file_name=f"{client.business_name}_extracted_statement_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_dl2:
            import io
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False, sheet_name="Transactions")
            st.download_button(
                label="📊 Download as Excel",
                data=excel_buffer.getvalue(),
                file_name=f"{client.business_name}_extracted_statement_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        st.write("")
        post_btn = st.button("💾 Post Verified Transactions to Ledger", type="primary", use_container_width=True)
        
        if post_btn:
            # Map skip selections back
            posted_count = 0
            skipped_count = 0
            posted_txs = []
            
            for index, row in edited_df.iterrows():
                orig_idx = df_review.iloc[index]["Index"]
                orig_tx = processed_batch[orig_idx]
                skip = row["Skip Import"]
                
                if skip:
                    skipped_count += 1
                    continue
                    
                cat_edited = str(row.get("Category", "")).strip()
                cat_final = cat_edited if cat_edited else orig_tx.get("category", None)
                if cat_final == "":
                    cat_final = None
                    
                # Create Database Transaction ORM entry
                db_tx = Transaction(
                    client_id=client_id,
                    account_id=account_id,
                    date=orig_tx["date"],
                    original_description=orig_tx["original_description"],
                    cleaned_description=row["Merchant"], # User can override Merchant in grid
                    debit=orig_tx["debit"],
                    credit=orig_tx["credit"],
                    amount=orig_tx["amount"],
                    balance=orig_tx["balance"],
                    category=cat_final,
                    is_transfer=orig_tx.get("is_transfer", False),
                    transfer_linked_acc=orig_tx.get("transfer_linked_acc", None),
                    confidence=float(row.get("Confidence", 0.0)),
                    review_required=bool(row.get("Review Required", False))
                )
                db.add(db_tx)
                # Category edits in the review grid are explicit confirmations and
                # become client-only desktop memory for the next statement.
                original_suggestion = str(df_review.iloc[index]["Category"]).strip()
                if cat_final and (cat_final != original_suggestion or not bool(row.get("Review Required", False))):
                    learn_mapping(db, client_id, row["Merchant"], cat_final, commit=False)
                posted_txs.append(db_tx)
                posted_count += 1
                
            db.commit() # Populate primary key IDs
            
            # Post each transaction to General Ledger and compute GST/ITCs
            from services.gst_service import calculate_transaction_gst
            from services.ledger_service import post_transaction_to_gl
            
            for tx in posted_txs:
                gst_val, itc_val = calculate_transaction_gst(tx, client, db=db)
                tx.gst_rate = 0.05
                tx.gst_amount = gst_val
                tx.itc_amount = itc_val
                db.add(tx)
                
            db.commit() # Save tax fields
            
            for tx in posted_txs:
                post_transaction_to_gl(db, tx)
                
            db.commit() # Finalize GL journal records
            
            # Log action to audit logs
            log_action(
                db=db,
                user_id=None,
                user_name=st.session_state.get("current_user_name", "System"),
                action_type="Import Bank Statement",
                client_id=client_id,
                client_name=client.business_name,
                details=f"General Ledger Post: {posted_count} entered | {skipped_count} duplicates skipped."
            )
            
            # Clear state batch after successful GL post
            del st.session_state["parsed_tx_batch"]
            st.success(f"Successfully posted {posted_count} transaction lines to General Ledger! {skipped_count} lines skipped.")
            st.rerun()
