import streamlit as st
import pandas as pd
from datetime import datetime
from services.client_service import get_clients, get_client_by_id
from services.extractor_service import parse_csv_statement, parse_pdf_statement
from services.duplicate_service import check_is_duplicate
from services.transfer_service import detect_internal_transfers
from services.audit_service import log_action
from core.models import Transaction, ClientBankAccount

def render_statement_import(db):
    """
    Renders the statement ingestion dashboard tab.
    """
    st.subheader("📥 Ingest Bank & Credit Card Statements")
    
    clients = get_clients(db)
    if not clients:
        st.warning("Please create a client profile before attempting to import statement files.")
        return
        
    # Form Layout
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        client_options = {c.business_name: c.id for c in clients}
        client_name = st.selectbox("Client Account", list(client_options.keys()))
        client_id = client_options[client_name]
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
        
    # File Uploader
    uploaded_file = st.file_uploader(
        "Drag & Drop Statement File (PDF or CSV)", 
        type=["pdf", "csv"], 
        help="Supports digital bank statements from RBC, TD, CIBC, BMO, and Scotiabank."
    )
    
    with st.expander("ℹ️ CSV Import Formatting Guide"):
        st.markdown("""
        To import transactions using a custom CSV file, ensure your file contains headers that the app can auto-detect. 
        
        ### Required Columns (Auto-Detected Headers):
        1. **Date**: Column header containing `Date` (e.g. *Transaction Date*, *Posting Date*).
        2. **Description**: Column header containing `Description`, `Memo`, `Detail`, `Particulars`, or `Name`.
        3. **Amount** (choose **one** of these options):
           * **Single Column**: Named `Amount` or `Value` (negative numbers for expenses/withdrawals, positive for deposits/revenue).
           * **Two Columns**: Named `Debit` (or *Withdrawal*) and `Credit` (or *Deposit*).
        
        ### Optional Columns:
        * **Balance**: Column header containing `Balance` to track the running account totals.
        * **Category**: Column header containing `Category`, `Type`, or `Account` to pre-assign ledger categorizations.
        
        ### Sample CSV Structure:
        """)
        sample_df = pd.DataFrame([
            {"Date": "2026-07-21", "Description": "Rogers Wireless", "Amount": -112.50, "Category": "Telephone Expense", "Balance": 1450.20},
            {"Date": "2026-07-21", "Description": "Client Deposit", "Amount": 2500.00, "Category": "Professional Fees", "Balance": 3950.20}
        ])
        st.dataframe(sample_df, use_container_width=True, hide_index=True)

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        file_type = uploaded_file.name.split(".")[-1].lower()
        
        st.write("")
        ingest_btn = st.button("🚀 Ingest & Extract Transactions", type="primary", use_container_width=True)
        
        if ingest_btn:
            with st.spinner("Extracting transactional tables and applying cleaning logic..."):
                try:
                    if file_type == "csv":
                        raw_txs = parse_csv_statement(file_bytes)
                    else:
                        raw_txs = parse_pdf_statement(file_bytes)
                        
                    if not raw_txs:
                        st.error("Failed to extract any transactions. Verify that the file contains digital text tables.")
                    else:
                        st.session_state["parsed_tx_batch"] = raw_txs
                        st.session_state["active_import_client_id"] = client_id
                        st.session_state["active_import_account_id"] = account_id
                        st.success(f"Successfully extracted {len(raw_txs)} transactions from statement file!")
                except Exception as e:
                    st.error(f"Extraction Pipeline failed: {e}")
                    
    # Render Review spreadsheet if batch exists in state
    if "parsed_tx_batch" in st.session_state and st.session_state.get("active_import_client_id") == client_id:
        batch = st.session_state["parsed_tx_batch"]
        account_id = st.session_state["active_import_account_id"]
        
        st.write("")
        st.subheader("📋 Transaction Ingestion Review Panel")
        st.info("Normalize merchant descriptions and inspect duplicates before importing into general ledger.")
        
        # Build bank map for internal transfer detection
        all_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
        bank_map = {a.id: a.account_name for a in all_accounts}
        
        # Apply transfer matcher on batch
        # Map account ID into batch objects
        for b in batch:
            b["account_id"] = account_id
            
        processed_batch = detect_internal_transfers(batch, bank_map)
        
        # Apply duplicate checks on batch
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
            
            review_data.append({
                "Index": idx,
                "Date": tx["date"].strftime("%Y-%m-%d"),
                "Original Memo": tx["original_description"],
                "Merchant": tx["cleaned_description"],
                "Amount ($ CAD)": f"${tx['amount']:,.2f}",
                "Balance ($)": f"${tx['balance']:,.2f}",
                "Category": tx.get("category", "") or "",
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
            df_review[["Date", "Original Memo", "Merchant", "Amount ($ CAD)", "Balance ($)", "Category", "Duplicate?", "Internal Transfer?", "Skip Import"]],
            use_container_width=True,
            num_rows="fixed",
            disabled=["Date", "Original Memo", "Amount ($ CAD)", "Balance ($)", "Duplicate?", "Internal Transfer?"]
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
                    confidence=1.0, # Rule based
                    review_required=False
                )
                db.add(db_tx)
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
