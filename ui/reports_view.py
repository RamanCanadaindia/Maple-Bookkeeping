import streamlit as st
import pandas as pd
from datetime import datetime
from services.client_service import get_clients, get_client_by_id
from services.report_service import compile_trial_balance, compile_income_statement, compile_balance_sheet
from services.gst_service import generate_gst_return_summary
from services.export_service import generate_excel_report, generate_pdf_report
from core.models import Transaction

def render_reports(db):
    """
    Renders corporate financial statements and GST Netfile return details.
    """
    st.subheader("📈 Financial Statements & Tax Reports")
    
    clients = get_clients(db)
    if not clients:
        st.warning("Please create a client profile before accessing reports.")
        return
        
    # Select Client
    client_options = {c.business_name: c.id for c in clients}
    client_name = st.selectbox("Select Client", list(client_options.keys()), key="reports_client_select")
    client_id = client_options[client_name]
    client = get_client_by_id(db, client_id)
    
    tab_pl, tab_bs, tab_tb, tab_gst, tab_monthly = st.tabs(["📊 Income Statement (P&L)", "⚖️ Balance Sheet", "🏁 Trial Balance", "🍁 GST Return Summary", "📅 Monthly Cash Flow"])
    
    with tab_pl:
        st.subheader("Income Statement (Profit & Loss)")
        st.markdown(f"**Period:** Fiscal Year End: *{client.fiscal_year_end}* | **Basis:** *{client.accounting_method}*")
        
        pl = compile_income_statement(db, client_id)
        
        # Display margins cards
        col_c1, col_c2, col_c3 = st.columns(3)
        col_c1.metric("Gross Revenue", f"${pl.get('Total Revenue', 0.0):,.2f}")
        col_c2.metric("Total Expenses", f"${pl.get('Total Expenses', 0.0):,.2f}")
        col_c3.metric("Net Book Income", f"${pl.get('Net Income', 0.0):,.2f}")
        
        st.markdown("---")
        
        # Revenues detail
        st.markdown("### 📈 Operating Revenue")
        if not pl["Revenues"]:
            st.info("No recorded revenue items.")
        else:
            rev_tbl = [{"Ledger Account": k, "Amount ($ CAD)": f"${v:,.2f}"} for k, v in pl["Revenues"].items()]
            st.table(pd.DataFrame(rev_tbl))
            st.markdown(f"**Total Revenue:** &nbsp;&nbsp;&nbsp;&nbsp; **`${pl['Total Revenue']:,.2f}`**")
            
        st.write("")
        # Expenses detail
        st.markdown("### 📉 Operating Expenses")
        if not pl["Expenses"]:
            st.info("No recorded expense items.")
        else:
            exp_tbl = [{"Ledger Account": k, "Amount ($ CAD)": f"${v:,.2f}"} for k, v in pl["Expenses"].items()]
            st.table(pd.DataFrame(exp_tbl))
            st.markdown(f"**Total Operating Expenses:** &nbsp;&nbsp;&nbsp;&nbsp; **`${pl['Total Expenses']:,.2f}`**")
            
        # Export options
        st.write("")
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
        st.subheader("🍁 CRA GST/HST return calculations")
        st.markdown(f"**Filing Period:** *{client.gst_period}* | **Accounting Mode:** *{client.gst_method}*")
        
        gst_ret = generate_gst_return_summary(db, client_id)
        
        if not gst_ret:
            st.info("No sales transactions to compute GST return.")
        else:
            # Layout the CRA NETFILE values card
            st.markdown(
                f"""
                <div style="background-color: #f7f9fa; padding: 1.5rem; border-radius: 8px; border: 1px solid #d3dbde; max-width: 600px; margin: 1rem 0;">
                    <h3 style="color:#c92a2a; margin-top:0;">🍁 GST Return Summary (Form GST34)</h3>
                    <table style="width:100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #ddd; height: 35px;">
                            <td><b>Line 101:</b> Taxable Sales & Revenue</td>
                            <td style="text-align:right;"><b>${gst_ret['gross_sales_revenue']:,.2f}</b></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #ddd; height: 35px;">
                            <td><b>Line 103:</b> GST/HST Collected or Payable</td>
                            <td style="text-align:right; color:#1e3d59;">${gst_ret['gst_collected_line103']:,.2f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #ddd; height: 35px;">
                            <td><b>Line 105:</b> Adjustments (GST collected)</td>
                            <td style="text-align:right;">$0.00</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #ddd; height: 35px;">
                            <td><b>Line 108:</b> Input Tax Credits (ITCs) Claimed</td>
                            <td style="text-align:right; color:#2b8a3e;">${gst_ret['itcs_claimed_line108']:,.2f}</td>
                        </tr>
                        <tr style="height: 45px;">
                            <td><b style="font-size:1.1rem; color:#c92a2a;">Line 109: Net Tax Remittance / Refund</b></td>
                            <td style="text-align:right;"><b style="font-size:1.1rem; color:#c92a2a;">${gst_ret['net_tax_due_line109']:,.2f}</b></td>
                        </tr>
                    </table>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Print instruction based on return status
            if gst_ret['net_tax_due_line109'] > 0:
                st.warning(f"⚠️ Net Tax Due to CRA: **`${gst_ret['net_tax_due_line109']:,.2f}`**")
            else:
                st.success(f"🎉 Net Refund Receivable from CRA: **`${abs(gst_ret['net_tax_due_line109']):,.2f}`**")
                
            # Export options
            st.write("")
            st.markdown("#### 📥 Export Statement")
            col_ex_gst1, col_ex_gst2 = st.columns(2)
            with col_ex_gst1:
                gst_rows = [
                    {"Line": "Line 101", "Description": "Taxable Sales & Revenue", "Amount": gst_ret['gross_sales_revenue']},
                    {"Line": "Line 103", "Description": "GST/HST Collected or Payable", "Amount": gst_ret['gst_collected_line103']},
                    {"Line": "Line 105", "Description": "Adjustments (GST collected)", "Amount": 0.0},
                    {"Line": "Line 108", "Description": "Input Tax Credits (ITCs) Claimed", "Amount": gst_ret['itcs_claimed_line108']},
                    {"Line": "Line 109", "Description": "Net Tax Remittance / Refund", "Amount": gst_ret['net_tax_due_line109']}
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
            # Prepare transaction dataframe
            tx_data = []
            for tx in txs:
                tx_data.append({
                    "date": tx.date,
                    "amount": tx.amount,
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
            
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("Cumulative Deposits (Income)", f"${total_inc:,.2f}")
            m_col2.metric("Cumulative Withdrawals (Expense)", f"${total_exp:,.2f}")
            m_col3.metric("Net Cash Flow", f"${net_flow:,.2f}", delta=f"${net_flow:,.2f}")
            
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
            
            ax.bar(x - width/2, monthly_summary['Income'], width, label='Income (Deposits)', color='#2e7d32', alpha=0.85)
            ax.bar(x + width/2, monthly_summary['Expense'], width, label='Expense (Withdrawals)', color='#c62828', alpha=0.85)
            ax.plot(x, monthly_summary['Net Flow'], color='#1976d2', marker='o', linewidth=2, label='Net Savings')
            
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
            
            with col_m_exp:
                st.markdown(f"**Expenses Breakdown for {sel_month}**")
                df_m_exp = df_m[df_m['type'] == 'Expense']
                if df_m_exp.empty:
                    st.info("No expenses in this month.")
                else:
                    cat_exp = df_m_exp.groupby('category')['abs_amount'].sum().sort_values(ascending=False).reset_index()
                    
                    fig_exp, ax_exp = plt.subplots(figsize=(6, 3.5))
                    sns.barplot(data=cat_exp, x='abs_amount', y='category', palette='Reds_r', ax=ax_exp)
                    ax_exp.set_title("Expenses by Category", fontsize=10, fontweight='bold')
                    ax_exp.set_xlabel("Amount ($)")
                    ax_exp.set_ylabel("")
                    ax_exp.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"${val:,.0f}"))
                    plt.tight_layout()
                    st.pyplot(fig_exp)
                    
                    st.dataframe(cat_exp.rename(columns={'category': 'Category', 'abs_amount': 'Amount ($)'}), use_container_width=True, hide_index=True)
                    
            with col_m_inc:
                st.markdown(f"**Income Breakdown for {sel_month}**")
                df_m_inc = df_m[df_m['type'] == 'Income']
                if df_m_inc.empty:
                    st.info("No income deposits in this month.")
                else:
                    cat_inc = df_m_inc.groupby('category')['abs_amount'].sum().sort_values(ascending=False).reset_index()
                    
                    fig_inc, ax_inc = plt.subplots(figsize=(6, 3.5))
                    sns.barplot(data=cat_inc, x='abs_amount', y='category', palette='Greens_r', ax=ax_inc)
                    ax_inc.set_title("Income by Category", fontsize=10, fontweight='bold')
                    ax_inc.set_xlabel("Amount ($)")
                    ax_inc.set_ylabel("")
                    ax_inc.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"${val:,.0f}"))
                    plt.tight_layout()
                    st.pyplot(fig_inc)
                    
                    st.dataframe(cat_inc.rename(columns={'category': 'Category', 'abs_amount': 'Amount ($)'}), use_container_width=True, hide_index=True)
