import streamlit as st
import os
import pandas as pd
from services.client_service import get_clients, get_client_by_id
from services.receipt_service import parse_receipt_file
from services.matcher_service import find_matching_transactions
from services.audit_service import log_action
from core.models import Transaction

def render_receipt_matcher(db):
    """
    Renders the receipt uploader, AI OCR classifier, and transaction matcher UI.
    """
    st.subheader("🧾 Receipt OCR Matcher & Audit Control")
    
    clients = get_clients(db)
    if not clients:
        st.warning("Please create a client profile before attempting to match receipts.")
        return
        
    # Select Client
    client_options = {c.business_name: c.id for c in clients}
    client_name = st.selectbox("Client Account", list(client_options.keys()), key="receipt_client_select")
    client_id = client_options[client_name]
    client = get_client_by_id(db, client_id)
    
    col_u1, col_u2 = st.columns([1, 1])
    
    with col_u1:
        st.markdown("### Ingest Receipt Doc")
        uploaded_receipt = st.file_uploader(
            "Upload Receipt (PNG, JPG, PDF)", 
            type=["png", "jpg", "jpeg", "pdf"],
            key="receipt_file_uploader"
        )
        
        if uploaded_receipt:
            file_bytes = uploaded_receipt.read()
            mime_type = uploaded_receipt.type
            filename = uploaded_receipt.name
            
            st.write("")
            analyze_btn = st.button("⚡ Run AI Receipt OCR", type="primary", use_container_width=True)
            
            if analyze_btn:
                with st.spinner("Extracting receipt data fields using Gemini 2.5 Pro..."):
                    try:
                        res = parse_receipt_file(file_bytes, mime_type)
                        st.session_state["parsed_receipt"] = res
                        st.session_state["uploaded_file_bytes"] = file_bytes
                        st.session_state["uploaded_filename"] = filename
                        st.success("Receipt scanned successfully!")
                    except Exception as e:
                        st.error(f"OCR Extraction failed: {e}")
                        
            # Render receipt preview if image
            if "image" in mime_type.lower():
                st.write("")
                st.image(file_bytes, caption="Receipt Ingestion Preview", use_container_width=True)
                
    with col_u2:
        st.markdown("### AI Extracted Receipt Details")
        
        if "parsed_receipt" not in st.session_state:
            st.info("Upload and analyze a receipt file to extract transaction values.")
        else:
            rc = st.session_state["parsed_receipt"]
            
            # Allow edits if AI misread
            r_merchant = st.text_input("Merchant", rc.get("merchant") or "Unknown")
            r_date = st.text_input("Transaction Date (YYYY-MM-DD)", rc.get("date") or "")
            r_amount = st.number_input("Total Amount ($)", value=float(rc.get("amount") or 0.0), format="%.2f")
            r_gst = st.number_input("GST Paid ($)", value=float(rc.get("gst") or 0.0), format="%.2f")
            
            st.markdown("---")
            st.markdown("### 🔍 Best Match Candidates in General Ledger")
            
            candidates = find_matching_transactions(db, client_id, r_amount, r_date)
            
            if not candidates:
                st.warning("No matching posted ledger transactions found for this amount and date.")
                st.info("Check if the statement containing this transaction has been ingested yet.")
            else:
                st.success(f"Found {len(candidates)} match candidates in the ledger!")
                
                # Build candidates table
                cand_rows = []
                cand_map = {}
                for idx, c_item in enumerate(candidates):
                    tx_obj = c_item["transaction"]
                    label = f"Match {idx+1}: {tx_obj.date.strftime('%Y-%m-%d')} | {tx_obj.cleaned_description} | ${abs(tx_obj.amount):,.2f} (Ref ID: {tx_obj.id})"
                    cand_map[label] = tx_obj.id
                    cand_rows.append(label)
                    
                selected_label = st.radio("Select Matching Transaction", cand_rows)
                selected_tx_id = cand_map[selected_label]
                
                st.write("")
                reconcile_btn = st.button("🔗 Reconcile & Link Audit Receipt", type="primary", use_container_width=True)
                
                if reconcile_btn:
                    # Save receipt file locally in storage
                    storage_dir = os.path.join(
                        r"C:\Users\admin\.gemini\antigravity\scratch\canadian_accounting_system\receipts",
                        str(client_id)
                    )
                    os.makedirs(storage_dir, exist_ok=True)
                    
                    local_filename = f"{selected_tx_id}_{st.session_state['uploaded_filename']}"
                    local_path = os.path.join(storage_dir, local_filename)
                    
                    with open(local_path, "wb") as f:
                        f.write(st.session_state["uploaded_file_bytes"])
                        
                    # Update transaction record
                    matched_tx = db.query(Transaction).filter(Transaction.id == selected_tx_id).first()
                    matched_tx.receipt_path = local_path
                    matched_tx.receipt_status = "Matched"
                    # Bind the user's manual category/tax edits if any
                    matched_tx.gst_amount = r_gst
                    db.add(matched_tx)
                    db.commit()
                    
                    log_action(
                        db=db,
                        user_id=None,
                        user_name=st.session_state.get("current_user_name", "System"),
                        action_type="Reconcile Receipt",
                        client_id=client_id,
                        client_name=client.business_name,
                        details=f"Linked receipt file {local_filename} to Transaction ID {selected_tx_id}."
                    )
                    
                    # Clear session state uploader cache
                    del st.session_state["parsed_receipt"]
                    del st.session_state["uploaded_file_bytes"]
                    del st.session_state["uploaded_filename"]
                    
                    st.success("Reconciliation complete! Receipt successfully linked to general ledger transaction.")
                    st.rerun()
