import streamlit as st
import pandas as pd
from datetime import datetime
from services.client_service import get_clients, get_client_by_id
from services.report_service import compile_trial_balance, compile_income_statement, compile_balance_sheet
from services.gst_service import generate_gst_return_summary
from services.export_service import generate_excel_report, generate_pdf_report
from core.models import Transaction

def render_custom_metric_card(label: str, value: str, icon: str, bg_color: str, text_color: str, icon_bg: str):
    """
    Renders a premium, accessible custom HTML metric card with robust contrast
    and red-green color-blind-safe palette styling.
    """
    import streamlit as st
    st.markdown(f"""
    <div style="background-color: white; border: 1px solid #e2e8f0; padding: 1.2rem; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; min-height: 100px;">
        <div>
            <div style="font-size: 0.8rem; color: #475569; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">{label}</div>
            <div style="font-size: 1.55rem; color: {text_color}; font-weight: 800; line-height: 1.1;">{value}</div>
        </div>
        <div style="width: 46px; height: 46px; border-radius: 50%; background-color: {icon_bg}; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; flex-shrink: 0; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.02);">
            {icon}
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_reports(db):
    """
    Renders corporate financial statements and GST Netfile return details.
    """
    st.subheader("📈 Financial Statements & Tax Reports")
    
    current_user = st.session_state.get("current_user")
    clients = get_clients(db, current_user)
    if not clients:
        st.warning("No client accounts are assigned to your profile.")
        return
        
    # Select Client
    client_options = {c.business_name: c.id for c in clients}
    
    from services.client_service import sync_global_active_client
    widget_key = "reports_client_select"
    on_change_cb = sync_global_active_client(widget_key, client_options)
    
    client_name = st.selectbox("Select Client", list(client_options.keys()), key=widget_key, on_change=on_change_cb)
    client_id = client_options[client_name]
    
    from services.client_service import verify_client_access
    if not verify_client_access(db, client_id, current_user):
        st.error("Access Denied: You do not have permissions to access this client's records.")
        return
        
    client = get_client_by_id(db, client_id)
    
    tab_pl, tab_bs, tab_tb, tab_gst, tab_monthly = st.tabs(["📊 Income Statement (P&L)", "⚖️ Balance Sheet", "🏁 Trial Balance", "🍁 GST Return Summary", "📅 Monthly Cash Flow"])
    
    with tab_pl:
        st.subheader("Income Statement (Profit & Loss)")
        
        # Period & Date Range Filter Bar
        col_p1, col_p2, col_p3 = st.columns([2, 2, 3])
        with col_p1:
            period_mode = st.selectbox(
                "📅 Report Period",
                ["Full History / All Time", "Custom Date Range"],
                key="pl_report_period_mode"
            )
            
        start_date_filter = None
        end_date_filter = None
        if period_mode == "Custom Date Range":
            with col_p2:
                custom_start = st.date_input("Start Date", key="pl_custom_start_date")
                start_date_filter = datetime.combine(custom_start, datetime.min.time())
            with col_p3:
                custom_end = st.date_input("End Date", key="pl_custom_end_date")
                end_date_filter = datetime.combine(custom_end, datetime.max.time())
        else:
            with col_p2:
                st.markdown(f"**Fiscal Year End:** *{client.fiscal_year_end}*")
            with col_p3:
                st.markdown(f"**Accounting Basis:** *{client.accounting_method}*")
                
        pl = compile_income_statement(db, client_id, start_date=start_date_filter, end_date=end_date_filter)
        account_items_map = pl.get("Account_Items", {})
        
        # Display margins cards using color-blind-safe premium HTML layout
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            render_custom_metric_card("Gross Revenue", f"${pl.get('Total Revenue', 0.0):,.2f}", "📈", "#f8fafc", "#0072B2", "#E6F0FA")
        with col_c2:
            render_custom_metric_card("Total Expenses", f"${pl.get('Total Expenses', 0.0):,.2f}", "📉", "#f8fafc", "#E69F00", "#FFF5E6")
        with col_c3:
            render_custom_metric_card("Net Book Income", f"${pl.get('Net Income', 0.0):,.2f}", "⚖️", "#f8fafc", "#0072B2", "#E6F0FA")
        
        st.markdown("---")
        
        from services.drilldown_service import calculate_account_total, reconcile_account
        
        all_rev_accounts = list(pl["Revenues"].keys())
        all_exp_accounts = list(pl["Expenses"].keys())
        all_accounts_list = all_rev_accounts + all_exp_accounts
        
        # --- PROMINENT TRANSACTION INSPECTOR CONTROLS ---
        col_ctrl1, col_ctrl2 = st.columns([3, 1])
        with col_ctrl1:
            inspect_default = st.session_state.get("pl_inspected_account", "-- Select an Account to View Transactions --")
            if inspect_default not in ["-- Select an Account to View Transactions --"] + all_accounts_list:
                inspect_default = "-- Select an Account to View Transactions --"
                
            selected_inspect_acc = st.selectbox(
                "🔍 **Instant Account Inspector (Select to View Transactions Directly):**",
                ["-- Select an Account to View Transactions --"] + all_accounts_list,
                index=(["-- Select an Account to View Transactions --"] + all_accounts_list).index(inspect_default),
                key="pl_account_inspector_select"
            )
            if selected_inspect_acc != "-- Select an Account to View Transactions --":
                st.session_state["pl_inspected_account"] = selected_inspect_acc
        with col_ctrl2:
            st.write("")
            expand_all_toggle = st.checkbox("📂 **Expand All Drill-Downs**", value=False, key="pl_expand_all_toggle")
            
        # If an account is selected in the Instant Inspector, render its full transaction table immediately
        if selected_inspect_acc and selected_inspect_acc != "-- Select an Account to View Transactions --":
            is_acc_rev = selected_inspect_acc in pl["Revenues"]
            acc_stmt_amt = pl["Revenues"].get(selected_inspect_acc, pl["Expenses"].get(selected_inspect_acc, 0.0))
            raw_acc_items = account_items_map.get(selected_inspect_acc, [])
            acc_dd_amt = calculate_account_total(raw_acc_items, is_revenue=is_acc_rev)
            acc_recon = reconcile_account(acc_stmt_amt, acc_dd_amt)
            
            st.markdown(
                f"""
                <div style="background-color:#eff6ff; border:1px solid #93c5fd; border-radius:8px; padding:1rem 1.25rem; margin:1rem 0;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <h4 style="margin:0; color:#1e3a8a;">🔍 Inspecting Account: <b>{selected_inspect_acc}</b> ({len(raw_acc_items)} Transactions)</h4>
                        <span style="font-weight:700; color:#1e40af; font-size:1.1rem;">Statement Balance: ${acc_stmt_amt:,.2f}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            if not raw_acc_items:
                st.info(f"No transactions found for account '{selected_inspect_acc}'.")
            else:
                insp_tbl_data = []
                for it in raw_acc_items:
                    dt_str = it["date"].strftime("%Y-%m-%d") if isinstance(it["date"], datetime) else str(it["date"])
                    insp_tbl_data.append({
                        "Date": dt_str,
                        "Vendor / Payee": it["vendor"],
                        "Description / Memo": it["description"],
                        "Debit": f"${it['debit']:,.2f}" if it['debit'] > 0 else "-",
                        "Credit": f"${it['credit']:,.2f}" if it['credit'] > 0 else "-",
                        "Net ($ CAD)": f"${it['net_amount']:,.2f}",
                        "GST ($)": f"${it['gst_amount']:,.2f}" if it['gst_amount'] > 0 else "-",
                        "ITC ($)": f"${it['itc_amount']:,.2f}" if (not is_acc_rev and it['itc_amount'] > 0) else "-",
                        "Source": it["source"],
                        "Bank Account": it["bank_account"],
                        "Ref #": str(it["reference"]),
                        "Tx ID": str(it["tx_id"]) if it["tx_id"] is not None else "-"
                    })
                st.dataframe(pd.DataFrame(insp_tbl_data), use_container_width=True, hide_index=True)
                
                col_ir1, col_ir2, col_ir3, col_ir4 = st.columns(4)
                with col_ir1:
                    st.metric("Statement Total", f"${acc_recon['statement_total']:,.2f}")
                with col_ir2:
                    st.metric("Drill-Down Total", f"${acc_recon['drilldown_total']:,.2f}")
                with col_ir3:
                    st.metric("Reconciliation Difference", f"${acc_recon['difference']:,.2f}")
                with col_ir4:
                    if acc_recon["is_reconciled"]:
                        st.success(f"**Status:** {acc_recon['status']}")
                    else:
                        st.error(f"**Status:** ⚠️ {acc_recon['status']}")
            st.markdown("---")
            
        def render_drilldown_section(category_name: str, statement_amt: float, is_rev: bool = False):
            raw_items = account_items_map.get(category_name, [])
            drilldown_amt = calculate_account_total(raw_items, is_revenue=is_rev)
            recon = reconcile_account(statement_amt, drilldown_amt)
            status_icon = "✅" if recon["is_reconciled"] else "⚠️"
            
            is_expanded = expand_all_toggle or (st.session_state.get("pl_inspected_account") == category_name)
            expander_title = f"{status_icon} **{category_name}** — `${statement_amt:,.2f}`  ({len(raw_items)} transaction{'s' if len(raw_items) != 1 else ''})"
            with st.expander(expander_title, expanded=is_expanded):
                if not raw_items:
                    st.info(f"No transactions found for {category_name}.")
                else:
                    # Build clean detail table for drill-down
                    tbl_data = []
                    for it in raw_items:
                        dt_str = it["date"].strftime("%Y-%m-%d") if isinstance(it["date"], datetime) else str(it["date"])
                        deb_str = f"${it['debit']:,.2f}" if it['debit'] > 0 else "-"
                        cred_str = f"${it['credit']:,.2f}" if it['credit'] > 0 else "-"
                        gst_str = f"${it['gst_amount']:,.2f}" if it['gst_amount'] > 0 else "-"
                        itc_str = f"${it['itc_amount']:,.2f}" if it['itc_amount'] > 0 else "-"
                        
                        row_entry = {
                            "Date": dt_str,
                            "Vendor / Payee": it["vendor"],
                            "Description / Memo": it["description"],
                            "Debit": deb_str,
                            "Credit": cred_str,
                            "Net ($ CAD)": f"${it['net_amount']:,.2f}",
                            "GST ($)": gst_str,
                        }
                        if not is_rev:
                            row_entry["ITC ($)"] = itc_str
                        row_entry["Source"] = it["source"]
                        row_entry["Bank Account"] = it["bank_account"]
                        row_entry["Ref #"] = str(it["reference"])
                        row_entry["Tx ID"] = str(it["tx_id"]) if it["tx_id"] is not None else "-"
                        tbl_data.append(row_entry)
                        
                    st.dataframe(pd.DataFrame(tbl_data), use_container_width=True, hide_index=True)
                    
                # Summary and Reconciliation Comparison Block
                st.markdown("##### 🔍 Reconciliation Summary")
                col_rc1, col_rc2, col_rc3, col_rc4 = st.columns(4)
                with col_rc1:
                    st.metric("Financial Statement", f"${recon['statement_total']:,.2f}")
                with col_rc2:
                    st.metric("Drill-Down Total", f"${recon['drilldown_total']:,.2f}")
                with col_rc3:
                    st.metric("Difference", f"${recon['difference']:,.2f}")
                with col_rc4:
                    if recon["is_reconciled"]:
                        st.success(f"**Status:** {recon['status']}")
                    else:
                        st.error(f"**Status:** ⚠️ {recon['status']}")
                        
                col_act1, col_act2 = st.columns([2, 3])
                with col_act1:
                    if st.button(f"📖 Filter in General Ledger", key=f"btn_gl_filter_{category_name}"):
                        st.session_state["ledger_category_filter"] = category_name
                        st.toast(f"Category filter set to '{category_name}'. Open the '📖 General Ledger' tab above.", icon="📌")
                with col_act2:
                    st.caption("Click to pre-set this category filter in the General Ledger browser.")
        
        # Revenues detail
        st.markdown("### 📈 Operating Revenue")
        if not pl["Revenues"]:
            st.info("No recorded revenue items.")
        else:
            for cat_name, amt in pl["Revenues"].items():
                render_drilldown_section(cat_name, amt, is_rev=True)
            st.markdown(f"**Total Operating Revenue:** &nbsp;&nbsp;&nbsp;&nbsp; **`${pl['Total Revenue']:,.2f}`**")
            
        st.write("")
        st.markdown("---")
        
        # Expenses detail
        st.markdown("### 📉 Operating Expenses")
        if not pl["Expenses"]:
            st.info("No recorded expense items.")
        else:
            for cat_name, amt in pl["Expenses"].items():
                render_drilldown_section(cat_name, amt, is_rev=False)
            st.markdown(f"**Total Operating Expenses:** &nbsp;&nbsp;&nbsp;&nbsp; **`${pl['Total Expenses']:,.2f}`**")
            
        # Export options
        st.write("")
        st.markdown("---")
        st.markdown("#### 📥 Export Statement")
        col_ex_pl1, col_ex_pl2 = st.columns(2)
        with col_ex_pl1:
            pl_rows = []
            for k, v in pl["Revenues"].items():
                pl_rows.append({"Type": "Operating Revenue", "Account": k, "Amount ($ CAD)": v})
            pl_rows.append({"Type": "Operating Revenue", "Account": "Total Revenue", "Amount ($ CAD)": pl["Total Revenue"]})
            for k, v in pl["Expenses"].items():
                pl_rows.append({"Type": "Operating Expense", "Account": k, "Amount ($ CAD)": v})
            pl_rows.append({"Type": "Operating Expense", "Account": "Total Operating Expenses", "Amount ($ CAD)": pl["Total Expenses"]})
            pl_rows.append({"Type": "Net Income", "Account": "Net Book Income", "Amount ($ CAD)": pl["Net Income"]})
            pl_df = pd.DataFrame(pl_rows)
            
            excel_pl = generate_excel_report(pl_df, sheet_name="Income Statement")
            st.download_button(
                label="📥 Export P&L to Excel (.xlsx)",
                data=excel_pl,
                file_name=f"{client.business_name.lower().replace(' ', '_')}_p_and_l.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_pl_excel"
            )
        with col_ex_pl2:
            pdf_pl_headers = ["Type", "Account", "Amount ($ CAD)"]
            pdf_pl_rows = []
            for row in pl_rows:
                pdf_pl_rows.append([row["Type"], row["Account"], f"${row['Amount ($ CAD)']:,.2f}"])
            
            pdf_pl = generate_pdf_report(
                title=f"Income Statement: {client.business_name} (FYE: {client.fiscal_year_end})",
                headers=pdf_pl_headers,
                rows=pdf_pl_rows,
                is_landscape=False
            )
            st.download_button(
                label="📄 Export P&L to PDF (.pdf)",
                data=pdf_pl,
                file_name=f"{client.business_name.lower().replace(' ', '_')}_p_and_l.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_btn_pl_pdf"
            )
            
    with tab_bs:
        st.subheader("Balance Sheet")
        st.markdown(f"**As at:** {datetime.utcnow().strftime('%B %d, %Y')} | **Client:** *{client.business_name}*")
        
        bs = compile_balance_sheet(db, client_id)
        
        # Assets Table
        st.markdown("### 🏦 ASSETS")
        if not bs["Assets"]:
            st.info("No recorded assets.")
        else:
            asset_tbl = [{"Asset Account": k, "Balance": f"${v:,.2f}"} for k, v in bs["Assets"].items()]
            st.table(pd.DataFrame(asset_tbl))
            st.markdown(f"**Total Assets:** &nbsp;&nbsp;&nbsp;&nbsp; **`${bs['Total Assets']:,.2f}`**")
            
        st.write("")
        # Liabilities Table
        st.markdown("### 💳 LIABILITIES")
        if not bs["Liabilities"]:
            st.info("No recorded liabilities.")
        else:
            liab_tbl = [{"Liability Account": k, "Balance": f"${v:,.2f}"} for k, v in bs["Liabilities"].items()]
            st.table(pd.DataFrame(liab_tbl))
            st.markdown(f"**Total Liabilities:** &nbsp;&nbsp;&nbsp;&nbsp; **`${bs['Total Liabilities']:,.2f}`**")
            
        st.write("")
        # Equity Table
        st.markdown("### 📁 SHAREHOLDER EQUITY")
        equity_tbl = [{"Equity Account": k, "Balance": f"${v:,.2f}"} for k, v in bs["Equity"].items()]
        st.table(pd.DataFrame(equity_tbl))
        st.markdown(f"**Total Equity:** &nbsp;&nbsp;&nbsp;&nbsp; **`${bs['Total Equity']:,.2f}`**")
        
        st.markdown("---")
        # Accounting equation validation card
        liab_equity = bs["Total Liabilities"] + bs["Total Equity"]
        if abs(bs["Total%s" % ' Assets'] - liab_equity) < 0.01:
            st.success(f"✅ Balanced! Assets (${bs['Total Assets']:,.2f}) = Liabilities + Equity (${liab_equity:,.2f})")
        else:
            st.error(f"❌ Unbalanced! Assets: ${bs['Total Assets']:,.2f} | Liabilities + Equity: ${liab_equity:,.2f}")
            
        # Export options
        st.write("")
        st.markdown("#### 📥 Export Statement")
        col_ex_bs1, col_ex_bs2 = st.columns(2)
        with col_ex_bs1:
            bs_rows = []
            for k, v in bs["Assets"].items():
                bs_rows.append({"Class": "Asset", "Account": k, "Balance": v})
            bs_rows.append({"Class": "Asset", "Account": "Total Assets", "Balance": bs["Total Assets"]})
            for k, v in bs["Liabilities"].items():
                bs_rows.append({"Class": "Liability", "Account": k, "Balance": v})
            bs_rows.append({"Class": "Liability", "Account": "Total Liabilities", "Balance": bs["Total Liabilities"]})
            for k, v in bs["Equity"].items():
                bs_rows.append({"Class": "Equity", "Account": k, "Balance": v})
            bs_rows.append({"Class": "Equity", "Account": "Total Equity", "Balance": bs["Total Equity"]})
            bs_df = pd.DataFrame(bs_rows)
            
            excel_bs = generate_excel_report(bs_df, sheet_name="Balance Sheet")
            st.download_button(
                label="📥 Export Balance Sheet to Excel (.xlsx)",
                data=excel_bs,
                file_name=f"{client.business_name.lower().replace(' ', '_')}_balance_sheet.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_bs_excel"
            )
        with col_ex_bs2:
            pdf_bs_headers = ["Class", "Account", "Balance ($ CAD)"]
            pdf_bs_rows = []
            for row in bs_rows:
                pdf_bs_rows.append([row["Class"], row["Account"], f"${row['Balance']:,.2f}"])
            
            pdf_bs = generate_pdf_report(
                title=f"Balance Sheet: {client.business_name} (As of {datetime.utcnow().strftime('%Y-%m-%d')})",
                headers=pdf_bs_headers,
                rows=pdf_bs_rows,
                is_landscape=False
            )
            st.download_button(
                label="📄 Export Balance Sheet to PDF (.pdf)",
                data=pdf_bs,
                file_name=f"{client.business_name.lower().replace(' ', '_')}_balance_sheet.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_btn_bs_pdf"
            )
            
    with tab_tb:
        st.subheader("Trial Balance Sheet Ledger Summary")
        tb_df = compile_trial_balance(db, client_id)
        
        if tb_df.empty:
            st.info("General Ledger contains no entries. Post statements to see Trial Balance.")
        else:
            # Render trial balance dataframe
            # Format numbers
            formatted_tb = tb_df.copy()
            formatted_tb["Debit"] = formatted_tb["Debit"].apply(lambda x: f"${x:,.2f}" if x != 0 else "-")
            formatted_tb["Credit"] = formatted_tb["Credit"].apply(lambda x: f"${x:,.2f}" if x != 0 else "-")
            
            st.dataframe(formatted_tb, use_container_width=True)
            
            # Export options
            st.write("")
            st.markdown("#### 📥 Export Statement")
            col_ex_tb1, col_ex_tb2 = st.columns(2)
            with col_ex_tb1:
                excel_tb = generate_excel_report(tb_df, sheet_name="Trial Balance")
                st.download_button(
                    label="📥 Export Trial Balance to Excel (.xlsx)",
                    data=excel_tb,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_trial_balance.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_btn_tb_excel"
                )
            with col_ex_tb2:
                pdf_tb_headers = list(tb_df.columns)
                pdf_tb_rows = []
                for _, row in tb_df.iterrows():
                    pdf_tb_rows.append([
                        str(row["Account Name"]),
                        f"${row['Debit']:,.2f}" if row["Debit"] != 0 else "-",
                        f"${row['Credit']:,.2f}" if row["Credit"] != 0 else "-"
                    ])
                pdf_tb = generate_pdf_report(
                    title=f"Trial Balance: {client.business_name}",
                    headers=pdf_tb_headers,
                    rows=pdf_tb_rows,
                    is_landscape=False
                )
                st.download_button(
                    label="📄 Export Trial Balance to PDF (.pdf)",
                    data=pdf_tb,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_trial_balance.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_btn_tb_pdf"
                )
            
    with tab_gst:
        st.subheader("🍁 CRA GST/HST Return Calculations (Form GST34)")
        
        # Period & Date Range Filter Bar for GST
        col_gp1, col_gp2, col_gp3 = st.columns([2, 2, 3])
        with col_gp1:
            gst_period_mode = st.selectbox(
                "📅 Filing Period Filter",
                ["Full History / All Time", "Custom Date Range"],
                key="gst_report_period_mode"
            )
            
        gst_start_filter = None
        gst_end_filter = None
        if gst_period_mode == "Custom Date Range":
            with col_gp2:
                gst_custom_start = st.date_input("Start Date", key="gst_custom_start_date")
                gst_start_filter = datetime.combine(gst_custom_start, datetime.min.time())
            with col_gp3:
                gst_custom_end = st.date_input("End Date", key="gst_custom_end_date")
                gst_end_filter = datetime.combine(gst_custom_end, datetime.max.time())
        else:
            with col_gp2:
                st.markdown(f"**Filing Frequency:** *{client.gst_period}*")
            with col_gp3:
                st.markdown(f"**Accounting Method:** *{client.gst_method}*")
                
        gst_ret = generate_gst_return_summary(db, client_id, start_date=gst_start_filter, end_date=gst_end_filter)
        
        if not gst_ret:
            st.info("No recorded transactions found for this period.")
        else:
            net_tax_color = "#E69F00" if gst_ret['net_tax_due_line109'] > 0 else "#0072B2"
            
            # Form GST34 Netfile Summary Card
            col_gst_card, col_gst_stats = st.columns([3, 2])
            with col_gst_card:
                st.markdown(
                    f"""
                    <div style="background-color: #f8fafc; padding: 1.5rem; border-radius: 8px; border: 1px solid #cbd5e1; margin: 0.5rem 0;">
                        <h4 style="color:#0f172a; margin-top:0;">🍁 Form GST34 Netfile Summary</h4>
                        <table style="width:100%; border-collapse: collapse; font-size: 0.95rem;">
                            <tr style="border-bottom: 1px solid #e2e8f0; height: 36px;">
                                <td><b>Line 101:</b> Taxable Sales & Revenue</td>
                                <td style="text-align:right;"><b>${gst_ret['gross_sales_revenue']:,.2f}</b></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e2e8f0; height: 36px;">
                                <td><b>Line 103:</b> GST/HST Collected or Payable</td>
                                <td style="text-align:right; color:#1e293b;"><b>${gst_ret['gst_collected_line103']:,.2f}</b></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e2e8f0; height: 36px;">
                                <td><b>Line 105:</b> Adjustments (GST collected)</td>
                                <td style="text-align:right;">$0.00</td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e2e8f0; height: 36px;">
                                <td><b>Line 108:</b> Input Tax Credits (ITCs) Claimed</td>
                                <td style="text-align:right; color:#0072B2;"><b>${gst_ret['itcs_claimed_line108']:,.2f}</b></td>
                            </tr>
                            <tr style="height: 48px;">
                                <td><b style="font-size:1.1rem; color:{net_tax_color};">Line 109: Net Tax Remittance / (Refund)</b></td>
                                <td style="text-align:right;"><b style="font-size:1.15rem; color:{net_tax_color};">${gst_ret['net_tax_due_line109']:,.2f}</b></td>
                            </tr>
                        </table>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                if gst_ret['net_tax_due_line109'] > 0:
                    st.warning(f"⚠️ Net Tax Payable to CRA: **`${gst_ret['net_tax_due_line109']:,.2f}`**")
                else:
                    st.success(f"🎉 Net Refund Receivable from CRA: **`${abs(gst_ret['net_tax_due_line109']):,.2f}`**")

            with col_gst_stats:
                st.markdown("##### 📊 Tax Treatment Overview")
                stats = gst_ret.get("treatment_stats", {})
                for treat_name, s_data in stats.items():
                    with st.container():
                        st.markdown(
                            f"""
                            <div style="background-color:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:0.6rem 0.8rem; margin-bottom:0.4rem;">
                                <div style="display:flex; justify-content:space-between; font-weight:600; font-size:0.9rem;">
                                    <span>{treat_name}</span>
                                    <span style="color:#0072B2;">ITC: ${s_data['itc_claimed']:,.2f}</span>
                                </div>
                                <div style="display:flex; justify-content:space-between; font-size:0.8rem; color:#64748b; margin-top:2px;">
                                    <span>Spend: ${s_data['spend']:,.2f} ({s_data['count']} txs)</span>
                                    <span>GST Paid: ${s_data['gst_paid']:,.2f}</span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
            
            st.markdown("---")
            
            # --- 1. LINE 101 & 103: SALES & GST COLLECTED BREAKDOWN ---
            st.markdown("### 📈 Line 101 & 103: Taxable Sales & GST Collected Breakdown")
            sales_items = gst_ret.get("sales_items", [])
            if not sales_items:
                st.info("No recorded sales transactions.")
            else:
                with st.expander(f"📂 View All Taxable Sales Transactions ({len(sales_items)} items) — Net Sales: `${gst_ret['gross_sales_revenue']:,.2f}` | GST: `${gst_ret['gst_collected_line103']:,.2f}`", expanded=False):
                    sales_df_data = []
                    for s in sales_items:
                        dt_s = s["date"].strftime("%Y-%m-%d") if isinstance(s["date"], datetime) else str(s["date"])
                        sales_df_data.append({
                            "Date": dt_s,
                            "Customer / Description": s["vendor"],
                            "Memo": s["description"],
                            "Category": s["category"],
                            "Total Invoiced": f"${s['total_amount']:,.2f}",
                            "Net Sales (Line 101)": f"${s['net_sales']:,.2f}",
                            "GST Collected (Line 103)": f"${s['gst_collected']:,.2f}",
                            "Type": s["type"]
                        })
                    st.dataframe(pd.DataFrame(sales_df_data), use_container_width=True, hide_index=True)
                    
                    # Sales summary metrics
                    col_sm1, col_sm2, col_sm3 = st.columns(3)
                    with col_sm1:
                        st.metric("Total Taxable Sales (Line 101)", f"${gst_ret['gross_sales_revenue']:,.2f}")
                    with col_sm2:
                        st.metric("Total GST Collected (Line 103)", f"${gst_ret['gst_collected_line103']:,.2f}")
                    with col_sm3:
                        st.metric("Contributing Invoices", len(sales_items))

            st.write("")
            st.markdown("---")
            
            # --- 2. LINE 108: INPUT TAX CREDITS (ITCs) BREAKDOWN BY CATEGORY ---
            st.markdown("### 📉 Line 108: Input Tax Credits (ITCs) Breakdown by Expense Category")
            itc_cats = gst_ret.get("itc_by_category", {})
            if not itc_cats:
                st.info("No recorded business expenses for Input Tax Credits.")
            else:
                st.caption("💡 **Click any category below to view contributing expense receipts and exact ITC claims:**")
                
                # Sort categories by total ITCs claimed descending
                sorted_cats = sorted(itc_cats.values(), key=lambda x: x["itc_claimed"], reverse=True)
                
                for c_info in sorted_cats:
                    cat_name = c_info["category"]
                    c_spend = c_info["total_spend"]
                    c_gst = c_info["gst_paid"]
                    c_itc = c_info["itc_claimed"]
                    c_items = c_info["items"]
                    
                    exp_label = f"📁 **{cat_name}** — ITCs Claimed: `${c_itc:,.2f}` | GST Paid: `${c_gst:,.2f}` | Spend: `${c_spend:,.2f}` ({len(c_items)} transactions)"
                    with st.expander(exp_label, expanded=False):
                        cat_df_data = []
                        for itm in c_items:
                            dt_i = itm["date"].strftime("%Y-%m-%d") if isinstance(itm["date"], datetime) else str(itm["date"])
                            cat_df_data.append({
                                "Date": dt_i,
                                "Vendor / Payee": itm["vendor"],
                                "Memo": itm["description"],
                                "Spend ($ CAD)": f"${itm['spend']:,.2f}",
                                "GST Paid (5%)": f"${itm['gst_paid']:,.2f}",
                                "ITC Claimed ($)": f"${itm['itc_claimed']:,.2f}",
                                "Treatment": itm["treatment"]
                            })
                        st.dataframe(pd.DataFrame(cat_df_data), use_container_width=True, hide_index=True)
                        
                        col_ic1, col_ic2, col_ic3, col_ic4 = st.columns(4)
                        with col_ic1:
                            st.metric("Category Spend", f"${c_spend:,.2f}")
                        with col_ic2:
                            st.metric("Total GST Paid", f"${c_gst:,.2f}")
                        with col_ic3:
                            st.metric("ITCs Claimable", f"${c_itc:,.2f}")
                        with col_ic4:
                            if st.button(f"📖 View in GL", key=f"btn_gst_gl_{cat_name}"):
                                st.session_state["ledger_category_filter"] = cat_name
                                st.toast(f"Category filter set to '{cat_name}'. Open the '📖 General Ledger' tab.", icon="📌")
            
            # Export options
            st.write("")
            st.markdown("---")
            st.markdown("#### 📥 Export GST Statement & Breakdown")
            col_ex_gst1, col_ex_gst2 = st.columns(2)
            with col_ex_gst1:
                gst_rows = [
                    {"Line": "Line 101", "Description": "Taxable Sales & Revenue", "Amount": gst_ret['gross_sales_revenue']},
                    {"Line": "Line 103", "Description": "GST/HST Collected or Payable", "Amount": gst_ret['gst_collected_line103']},
                    {"Line": "Line 105", "Description": "Adjustments (GST collected)", "Amount": 0.0},
                    {"Line": "Line 108", "Description": "Input Tax Credits (ITCs) Claimed", "Amount": gst_ret['itcs_claimed_line108']},
                    {"Line": "Line 109", "Description": "Net Tax Remittance / (Refund)", "Amount": gst_ret['net_tax_due_line109']}
                ]
                gst_df = pd.DataFrame(gst_rows)
                excel_gst = generate_excel_report(gst_df, sheet_name="GST Return")
                st.download_button(
                    label="📥 Export GST Return to Excel (.xlsx)",
                    data=excel_gst,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_gst_return.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_btn_gst_excel"
                )
            with col_ex_gst2:
                pdf_gst_headers = ["Line", "Description", "Amount ($ CAD)"]
                pdf_gst_rows = []
                for row in gst_rows:
                    pdf_gst_rows.append([row["Line"], row["Description"], f"${row['Amount']:,.2f}"])
                
                pdf_gst = generate_pdf_report(
                    title=f"GST Return Summary: {client.business_name} ({client.gst_period})",
                    headers=pdf_gst_headers,
                    rows=pdf_gst_rows,
                    is_landscape=False
                )
                st.download_button(
                    label="📄 Export GST Return to PDF (.pdf)",
                    data=pdf_gst,
                    file_name=f"{client.business_name.lower().replace(' ', '_')}_gst_return.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_btn_gst_pdf"
                )
                
    with tab_monthly:
        st.subheader("📅 Monthly Income & Expense Analysis")
        st.markdown("Visual breakdown of deposits (income) and withdrawals (expenses) by month, plus category distributions.")
        
        # Query client transactions from DB
        txs = db.query(Transaction).filter(Transaction.client_id == client_id, Transaction.is_duplicate == False).all()
        
        if not txs:
            st.info("No transaction records found for this client. Import bank statements first to view this analysis.")
        else:
            # Load bank accounts mapping
            from core.models import ClientBankAccount
            bank_accounts = db.query(ClientBankAccount).filter(ClientBankAccount.client_id == client_id).all()
            bank_map = {a.id: a.account_name for a in bank_accounts}

            # Prepare transaction dataframe
            tx_data = []
            for tx in txs:
                tx_data.append({
                    "date": tx.date,
                    "amount": tx.amount,
                    "account": bank_map.get(tx.account_id, "Unknown"),
                    "category": tx.category or "Uncategorized",
                    "description": tx.cleaned_description or ""
                })
            df = pd.DataFrame(tx_data)
            
            # Formats
            df['date'] = pd.to_datetime(df['date'])
            df['month_str'] = df['date'].dt.strftime('%Y-%m')
            df['type'] = df['amount'].apply(lambda x: 'Income' if x > 0 else 'Expense')
            df['abs_amount'] = df['amount'].abs()
            
            # Cumulative Summary Metrics
            total_inc = df[df['type'] == 'Income']['abs_amount'].sum()
            total_exp = df[df['type'] == 'Expense']['abs_amount'].sum()
            net_flow = total_inc - total_exp
            
            # Display cumulative metrics using premium color-blind-safe HTML cards
            m_col1, m_col2, m_col3 = st.columns(3)
            with m_col1:
                render_custom_metric_card("Cumulative Deposits (Income)", f"${total_inc:,.2f}", "📥", "#f8fafc", "#0072B2", "#E6F0FA")
            with m_col2:
                render_custom_metric_card("Cumulative Withdrawals (Expense)", f"${total_exp:,.2f}", "📤", "#f8fafc", "#E69F00", "#FFF5E6")
            with m_col3:
                render_custom_metric_card("Net Cash Flow", f"${net_flow:,.2f}", "💰", "#f8fafc", "#0072B2", "#E6F0FA")
            
            st.write("")
            
            # Monthly totals
            monthly_summary = df.groupby(['month_str', 'type'])['abs_amount'].sum().unstack(fill_value=0.0).reset_index()
            if 'Income' not in monthly_summary.columns:
                monthly_summary['Income'] = 0.0
            if 'Expense' not in monthly_summary.columns:
                monthly_summary['Expense'] = 0.0
            monthly_summary['Net Flow'] = monthly_summary['Income'] - monthly_summary['Expense']
            
            # Trend Chart
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
            
            sns.set_theme(style="whitegrid")
            fig, ax = plt.subplots(figsize=(10, 4.5))
            
            x = np.arange(len(monthly_summary))
            width = 0.35
            
            ax.bar(x - width/2, monthly_summary['Income'], width, label='Income (Deposits) [Pattern: ///]', color='#0072B2', hatch='///', alpha=0.85)
            ax.bar(x + width/2, monthly_summary['Expense'], width, label='Expense (Withdrawals) [Pattern: \\\\\\]', color='#E69F00', hatch='\\\\\\', alpha=0.85)
            ax.plot(x, monthly_summary['Net Flow'], color='#1F3A5F', marker='o', linewidth=2.5, label='Net Savings (Solid)')
            
            ax.set_title("Income vs Expense by Month", fontsize=12, fontweight='bold', pad=10)
            ax.set_xticks(x)
            ax.set_xticklabels(monthly_summary['month_str'], rotation=30, ha='right')
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"${val:,.0f}"))
            ax.legend(frameon=True, facecolor='white', edgecolor='none')
            plt.tight_layout()
            st.pyplot(fig)
            
            # Monthly drill-down
            st.markdown("---")
            st.markdown("### 🔍 Monthly Category Drill-Down")
            months = sorted(df['month_str'].unique(), reverse=True)
            sel_month = st.selectbox("Select Month to Analyze", months, key="monthly_drill_select")
            
            df_m = df[df['month_str'] == sel_month]
            
            col_m_exp, col_m_inc = st.columns(2)
            
            # Group by category and sum net amounts
            cat_groups = df_m.groupby('category')['amount'].sum().reset_index()
            
            # Classify into Income vs Expense based on account type/net sign
            income_rows = []
            expense_rows = []
            
            for _, row in cat_groups.iterrows():
                cat = row['category']
                net_val = row['amount']
                cat_lower = cat.lower()
                
                # Check if it is a revenue/income account
                is_income_acc = (
                    ("revenue" in cat_lower or "sales" in cat_lower or "fees" in cat_lower or "income" in cat_lower or "deposit" in cat_lower)
                    and "bank fees" not in cat_lower
                ) or (cat_lower == "uncategorized" and net_val >= 0)
                
                if is_income_acc:
                    # Revenue/Sales: Normal balance is positive (net credit)
                    if net_val != 0.0:
                        income_rows.append({
                            "category": cat,
                            "abs_amount": abs(net_val) # Net revenue magnitude
                        })
                else:
                    # Expense: Normal balance is negative (net debit/payment)
                    if net_val != 0.0:
                        expense_rows.append({
                            "category": cat,
                            "abs_amount": abs(net_val) # Net expense magnitude
                        })
                        
            cat_inc = pd.DataFrame(income_rows) if income_rows else pd.DataFrame(columns=['category', 'abs_amount'])
            cat_exp = pd.DataFrame(expense_rows) if expense_rows else pd.DataFrame(columns=['category', 'abs_amount'])
            
            # Sort descending by amount
            if not cat_inc.empty:
                cat_inc = cat_inc.sort_values(by='abs_amount', ascending=False).reset_index(drop=True)
            if not cat_exp.empty:
                cat_exp = cat_exp.sort_values(by='abs_amount', ascending=False).reset_index(drop=True)
                
            # --- 📈 Expense Analysis vs Revenue Widget ---
            st.markdown("---")
            st.markdown("### 📊 Expense Analysis vs Revenue")
            
            # Calculate Revenue & Operating Expenses
            total_rev = cat_inc['abs_amount'].sum() if not cat_inc.empty else 0.0
            
            # Identify excluded categories (Transfers/personal drawings)
            excluded_categories = ["Personal", "CC Payment", "Transfer", "Credit Card Payment", "Personal Drawing"]
            
            operating_rows = []
            excluded_rows = []
            
            for _, row in cat_exp.iterrows():
                cat = row['category']
                if any(x.lower() in cat.lower() for x in excluded_categories):
                    excluded_rows.append(row)
                else:
                    operating_rows.append(row)
                    
            df_operating = pd.DataFrame(operating_rows) if operating_rows else pd.DataFrame(columns=['category', 'abs_amount'])
            df_excluded = pd.DataFrame(excluded_rows) if excluded_rows else pd.DataFrame(columns=['category', 'abs_amount'])
            
            total_opex = df_operating['abs_amount'].sum() if not df_operating.empty else 0.0
            net_income_val = total_rev - total_opex
            exp_ratio_val = (total_opex / total_rev * 100) if total_rev > 0 else 0.0
            
            # Metric Cards using color-blind-safe premium HTML layout
            met_col1, met_col2, met_col3, met_col4 = st.columns(4)
            with met_col1:
                render_custom_metric_card("Total Revenue", f"${total_rev:,.2f}", "📈", "#f8fafc", "#0072B2", "#E6F0FA")
            with met_col2:
                render_custom_metric_card("Operating Expenses", f"${total_opex:,.2f}", "💳", "#f8fafc", "#E69F00", "#FFF5E6")
            with met_col3:
                render_custom_metric_card("Net Income", f"${net_income_val:,.2f}", "⚖️", "#f8fafc", "#0072B2", "#E6F0FA")
            with met_col4:
                render_custom_metric_card("Expense Ratio", f"{exp_ratio_val:.2f}%", "％", "#f8fafc", "#1F3A5F", "#EAEFF5")
            
            st.write("")
            
            # Build chart data
            chart_data = []
            if total_rev > 0:
                chart_data.append({
                    "category": "Total Revenue",
                    "amount": total_rev,
                    "percentage": 100.0,
                    "color": "#0072B2", # Deep blue
                    "hatch": ""
                })
                for _, row in df_operating.iterrows():
                    pct = (row['abs_amount'] / total_rev) * 100
                    chart_data.append({
                        "category": row['category'],
                        "amount": row['abs_amount'],
                        "percentage": pct,
                        "color": "#E69F00", # Warm orange
                        "hatch": "///"
                    })
            else:
                for _, row in df_operating.iterrows():
                    chart_data.append({
                        "category": row['category'],
                        "amount": row['abs_amount'],
                        "percentage": 0.0,
                        "color": "#E69F00",
                        "hatch": "///"
                    })
                    
            df_chart = pd.DataFrame(chart_data)
            
            if not df_chart.empty:
                # Render clean horizontal bar chart
                fig_analysis, ax_analysis = plt.subplots(figsize=(10, 4.5))
                colors = df_chart['color'].tolist()
                hatches = df_chart['hatch'].tolist()
                
                bars = ax_analysis.barh(df_chart['category'][::-1], df_chart['percentage'][::-1], color=colors[::-1], height=0.55)
                
                # Apply hatches
                for bar, hatch in zip(bars, hatches[::-1]):
                    bar.set_hatch(hatch)
                
                # Add text labels on the bars
                for bar, pct, amt in zip(bars, df_chart['percentage'][::-1], df_chart['amount'][::-1]):
                    width = bar.get_width()
                    if pct == 100.0:
                        ax_analysis.text(width + 1, bar.get_y() + bar.get_height()/2, f"${amt:,.2f} — 100%", 
                                         va='center', ha='left', fontweight='bold', fontsize=9, color="#0072B2")
                    else:
                        ax_analysis.text(width + 1, bar.get_y() + bar.get_height()/2, f"{pct:.2f}% (${amt:,.2f})", 
                                         va='center', ha='left', fontsize=9, color="#E69F00")
                
                ax_analysis.set_title(f"Revenue and Expenses by Category (% of Revenue) - {sel_month}", fontsize=11, fontweight='bold', pad=12)
                ax_analysis.set_xlabel("% of Revenue")
                ax_analysis.set_xlim(0, 115) # Leave space for text labels
                ax_analysis.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"{val:.0f}%"))
                sns.despine(left=True, bottom=True)
                plt.tight_layout()
                st.pyplot(fig_analysis)
                
                # Render Data Table
                table_rows = []
                if total_rev > 0:
                    table_rows.append({
                        "Category": "Total Revenue",
                        "Amount ($)": f"{total_rev:,.2f}",
                        "% of Revenue": "100.00%"
                    })
                for _, row in df_operating.iterrows():
                    pct = (row['abs_amount'] / total_rev * 100) if total_rev > 0 else 0.0
                    table_rows.append({
                        "Category": row['category'],
                        "Amount ($)": f"{row['abs_amount']:,.2f}",
                        "% of Revenue": f"{pct:.2f}%"
                    })
                st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
                
            # Excluded items disclaimer
            if not df_excluded.empty:
                ex_details = []
                for _, row in df_excluded.iterrows():
                    ex_details.append(f"{row['category']} (${row['abs_amount']:,.2f})")
                st.info(f"ℹ️ Excluded from operating expenses: {', '.join(ex_details)}")
                
            st.markdown("---")
            with col_m_exp:
                st.markdown(f"**Expenses Breakdown for {sel_month}**")
                if cat_exp.empty:
                    st.info("No expenses in this month.")
                else:
                    fig_exp, ax_exp = plt.subplots(figsize=(6, 3.5))
                    # Color blind safe warm orange bars with hatch pattern
                    sns.barplot(data=cat_exp, x='abs_amount', y='category', color='#E69F00', hatch='///', ax=ax_exp)
                    ax_exp.set_title("Expenses by Category [Pattern: ///]", fontsize=10, fontweight='bold')
                    ax_exp.set_xlabel("Amount ($)")
                    ax_exp.set_ylabel("")
                    ax_exp.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"${val:,.0f}"))
                    plt.tight_layout()
                    st.pyplot(fig_exp)
                    
                    st.dataframe(cat_exp.rename(columns={'category': 'Category', 'abs_amount': 'Amount ($)'}), use_container_width=True, hide_index=True)
                    
            with col_m_inc:
                st.markdown(f"**Income Breakdown for {sel_month}**")
                if cat_inc.empty:
                    st.info("No income deposits in this month.")
                else:
                    fig_inc, ax_inc = plt.subplots(figsize=(6, 3.5))
                    # Color blind safe deep blue bars with hatch pattern
                    sns.barplot(data=cat_inc, x='abs_amount', y='category', color='#0072B2', hatch='\\\\\\', ax=ax_inc)
                    ax_inc.set_title("Income by Category", fontsize=10, fontweight='bold')
                    ax_inc.set_xlabel("Amount ($)")
                    ax_inc.set_ylabel("")
                    ax_inc.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"${val:,.0f}"))
                    plt.tight_layout()
                    st.pyplot(fig_inc)
                    
                    st.dataframe(cat_inc.rename(columns={'category': 'Category', 'abs_amount': 'Amount ($)'}), use_container_width=True, hide_index=True)
                    
            # Detailed Transactions list for the selected month
            st.markdown("---")
            st.markdown("### 📋 Monthly Transactions Detail")
            
            categories = ["All Categories"] + sorted(list(df_m["category"].unique()))
            selected_cat = st.selectbox("Filter transactions by category", categories, key="monthly_tx_cat_select")
            
            if selected_cat != "All Categories":
                df_detailed = df_m[df_m["category"] == selected_cat]
            else:
                df_detailed = df_m
                
            if df_detailed.empty:
                st.info("No transactions found for this selection.")
            else:
                df_show = df_detailed[["date", "account", "category", "description", "amount"]].copy()
                df_show["date"] = df_show["date"].dt.strftime("%Y-%m-%d")
                df_show["amount"] = df_show["amount"].apply(lambda x: f"${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}")
                
                st.dataframe(
                    df_show.rename(columns={
                        "date": "Date",
                        "account": "Account",
                        "category": "Category",
                        "description": "Description / Memo",
                        "amount": "Amount ($ CAD)"
                    }),
                    use_container_width=True,
                    hide_index=True
                )
