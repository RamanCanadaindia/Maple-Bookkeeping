import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import json
import calendar
from sqlalchemy.orm import Session
from core.models import Reminder, ReminderType, Notification, EmailTemplate, EmailHistory, ReminderSettings, SchedulerRun, Client
from services.gmail_service import (
    get_oauth_flow,
    get_gmail_service,
    send_gmail_email,
    parse_template,
    encrypt_token,
    decrypt_token
)
from services.reminder_scheduler import run_scheduler_cycle, advance_due_date, get_period_dates, calculate_send_datetime_utc

def render_reminder_centre(db: Session, section: str):
    """
    Renders the Reminder Centre module pages based on selected sidebar section.
    """
    # Global check for authorization
    is_authorized = st.session_state.get("authenticated") and st.session_state.get("current_user_role") in ("Admin", "Accountant")
    
    # Process Google OAuth Callback parameter if present
    query_params = st.query_params
    if "code" in query_params:
        if not is_authorized:
            st.error("Access Denied: You do not have permissions to connect Gmail.")
        else:
            auth_code = query_params["code"]
            with st.spinner("Exchanging OAuth authorization code..."):
                try:
                    # Resolve redirect URI
                    try:
                        redirect_uri = st.secrets.get("GOOGLE_REDIRECT_URI", "http://localhost:8501/")
                    except Exception:
                        redirect_uri = "http://localhost:8501/"
                        
                    flow = get_oauth_flow(redirect_uri)
                    token_info = exchange_code_for_token_helper(flow, auth_code)
                    encrypted = encrypt_token(json.dumps(token_info))
                    
                    settings = db.query(ReminderSettings).first()
                    if not settings:
                        settings = ReminderSettings()
                        db.add(settings)
                    settings.gmail_oauth_token = encrypted
                    settings.gmail_authorized_email = "Pending Verification..."
                    db.commit()
                    
                    # Fetch profile email
                    try:
                        service, _ = get_gmail_service(encrypted)
                        profile = service.users().getProfile(userId='me').execute()
                        settings.gmail_authorized_email = profile.get("emailAddress", "connected@gmail.com")
                        db.commit()
                    except Exception:
                        pass
                        
                    st.success("Successfully connected your Gmail account!")
                    st.query_params.clear()
                    st.rerun()
                except Exception as oauth_err:
                    st.error(f"Gmail connection failed: {oauth_err}")

    if section == "Dashboard":
        render_dashboard_tab(db)
    elif section == "Client Reminders":
        render_reminders_tab(db, is_authorized)
    elif section == "Email Templates":
        render_templates_tab(db, is_authorized)
    elif section == "Email History":
        render_history_tab(db)
    elif section == "Settings":
        render_settings_tab(db, is_authorized)

def exchange_code_for_token_helper(flow, code: str) -> dict:
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    }

def render_dashboard_tab(db: Session):
    st.subheader("📊 Operations Dashboard")
    
    # 1. Metric Cards
    # Today's Vancouver Date
    import pytz
    vancouver_tz = pytz.timezone("America/Vancouver")
    now_utc = datetime.utcnow()
    now_vancouver = datetime.now(pytz.utc).astimezone(vancouver_tz)
    today_vancouver = now_vancouver.date()
    
    start_of_today_utc = vancouver_tz.localize(datetime.combine(today_vancouver, time.min)).astimezone(pytz.utc)
    end_of_today_utc = vancouver_tz.localize(datetime.combine(today_vancouver, time.max)).astimezone(pytz.utc)
    
    # Completed This Month
    first_day_of_month = today_vancouver.replace(day=1)
    start_of_month_utc = vancouver_tz.localize(datetime.combine(first_day_of_month, time.min)).astimezone(pytz.utc)
    
    # Metrics calculations
    today_reminders_count = db.query(Notification).filter(
        Notification.scheduled_send_date >= start_of_today_utc,
        Notification.scheduled_send_date <= end_of_today_utc
    ).count()
    
    next_7_days_count = db.query(Notification).filter(
        Notification.scheduled_send_date > end_of_today_utc,
        Notification.scheduled_send_date <= end_of_today_utc + timedelta(days=7)
    ).count()
    
    overdue_count = db.query(Reminder).filter(
        Reminder.status == "ACTIVE",
        Reminder.current_due_date < datetime.combine(today_vancouver, time.min)
    ).count()
    
    completed_this_month = db.query(Notification).filter(
        Notification.status == "SENT",
        Notification.sent_at >= start_of_month_utc
    ).count()
    
    failed_emails = db.query(Notification).filter(
        Notification.status == "FAILED"
    ).count()
    
    # Render KPI layout
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Today's Reminders", today_reminders_count)
    col2.metric("Next 7 Days", next_7_days_count)
    col3.metric("Overdue Filing Oblig.", overdue_count, delta=f"{overdue_count} overdue" if overdue_count else None, delta_color="inverse")
    col4.metric("Sent This Month", completed_this_month)
    col5.metric("Failed Emails", failed_emails, delta=f"{failed_emails} failed" if failed_emails else None, delta_color="inverse")
    
    # Audit log card
    last_run = db.query(SchedulerRun).order_by(SchedulerRun.started_at.desc()).first()
    st.write("")
    if last_run:
        status_color = "🟢" if last_run.status == "SUCCESS" else "🔴"
        st.info(
            f"**Last Scheduler Run**: {status_color} {last_run.status} | "
            f"Checked: {last_run.reminders_checked} | Sent: {last_run.emails_sent} | Failed: {last_run.emails_failed} | "
            f"Finished: {last_run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC') if last_run.finished_at else 'N/A'}"
        )
    else:
        st.info("No scheduler run history found.")
        
    st.markdown("### 📅 Upcoming Reminders (Next 30 Days)")
    thirty_days_limit = end_of_today_utc + timedelta(days=30)
    
    upcoming_notifs = db.query(Notification).filter(
        Notification.status == "PENDING",
        Notification.scheduled_send_date >= start_of_today_utc,
        Notification.scheduled_send_date <= thirty_days_limit
    ).order_by(Notification.scheduled_send_date.asc()).all()
    
    if not upcoming_notifs:
        st.success("No pending email notifications scheduled for the next 30 days.")
    else:
        records = []
        for n in upcoming_notifs:
            rem = n.reminder
            records.append({
                "Client": rem.client.business_name if rem.client else "Unknown",
                "Email": n.recipient_email,
                "Filing Due Date": rem.current_due_date.strftime("%Y-%m-%d"),
                "Reminder Offset": f"{n.offset_days} days before",
                "Send Target (Local)": n.scheduled_send_date.astimezone(vancouver_tz).strftime("%Y-%m-%d %I:%M %p"),
                "Reminder Type": rem.reminder_type.name if rem.reminder_type else "General"
            })
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

def render_reminders_tab(db: Session, is_authorized: bool):
    st.subheader("📅 Client Reminder Schedules")
    
    # Search and Filter
    col_s1, col_s2, col_s3 = st.columns([4, 4, 4])
    with col_s1:
        search_query = st.text_input("Search Client or Business", placeholder="e.g. ABC Corp")
    with col_s2:
        types = ["All Types"] + [t.name for t in db.query(ReminderType).all()]
        selected_type = st.selectbox("Filter by Reminder Type", types)
    with col_s3:
        statuses = ["All Statuses", "ACTIVE", "PAUSED", "CANCELLED"]
        selected_status = st.selectbox("Filter by Status", statuses)
        
    # Query logic
    query = db.query(Reminder)
    if search_query:
        query = query.join(Client).filter(
            (Client.business_name.ilike(f"%{search_query}%")) | 
            (Client.email.ilike(f"%{search_query}%"))
        )
    if selected_type != "All Types":
        query = query.join(ReminderType).filter(ReminderType.name == selected_type)
    if selected_status != "All Statuses":
        query = query.filter(Reminder.status == selected_status)
        
    reminders = query.all()
    
    if not reminders:
        st.info("No active reminder profiles found matching your filters.")
    else:
        st.markdown(f"Found **{len(reminders)}** client reminder configuration(s):")
        
        rem_records = []
        for r in reminders:
            rem_records.append({
                "ID": r.id,
                "Client": r.client.business_name if r.client else "Unknown",
                "Filing Type": r.reminder_type.name if r.reminder_type else "Unknown",
                "Next Due Date": r.current_due_date.strftime("%Y-%m-%d"),
                "Frequency": r.frequency,
                "Interval": r.recurrence_interval,
                "Offsets": r.reminder_offsets,
                "Status": r.status,
                "Email": r.client.email if r.client else "N/A"
            })
            
        df_rems = pd.DataFrame(rem_records)
        
        # Data Editor or Display Grid
        if is_authorized:
            st.warning("Double-click cells to edit next due dates, frequency, or offsets directly. Delete rows to remove reminders.")
            edited_df = st.data_editor(
                df_rems,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", disabled=True),
                    "Client": st.column_config.TextColumn("Client", disabled=True),
                    "Filing Type": st.column_config.TextColumn("Filing Type", disabled=True),
                    "Email": st.column_config.TextColumn("Email Address", disabled=True),
                    "Next Due Date": st.column_config.DateColumn("Next Due Date", required=True),
                    "Frequency": st.column_config.SelectboxColumn("Frequency", options=["One Time", "Monthly", "Quarterly", "Annually", "Custom"], required=True),
                    "Interval": st.column_config.NumberColumn("Recurrence Interval (Multiplier)", min_value=1, step=1, required=True),
                    "Offsets": st.column_config.TextColumn("Offsets (Comma separated)", required=True),
                    "Status": st.column_config.SelectboxColumn("Status", options=["ACTIVE", "PAUSED", "CANCELLED"], required=True)
                },
                disabled=["ID", "Client", "Filing Type", "Email"],
                num_rows="dynamic",
                use_container_width=True,
                key="reminder_grid_editor"
            )
            
            # Deletions catch
            grid_state = st.session_state.get("reminder_grid_editor", {})
            if grid_state and "deleted_rows" in grid_state and grid_state["deleted_rows"]:
                with st.spinner("Deleting selected reminder(s) and clearing schedules..."):
                    for idx in grid_state["deleted_rows"]:
                        rem_id = int(df_rems.iloc[idx]["ID"])
                        db_rem = db.query(Reminder).filter(Reminder.id == rem_id).first()
                        if db_rem:
                            # Delete associated pending notifications
                            db.query(Notification).filter(Notification.reminder_id == rem_id).delete(synchronize_session=False)
                            db.delete(db_rem)
                    db.commit()
                st.toast("Deleted reminder schedules successfully!", icon="🗑️")
                st.rerun()
                
            # Updates catch
            for idx, row in edited_df.iterrows():
                orig = df_rems.iloc[idx]
                r_id = int(row["ID"])
                
                # Check for edits
                due_dt_changed = str(row["Next Due Date"]) != str(orig["Next Due Date"])
                freq_changed = row["Frequency"] != orig["Frequency"]
                int_changed = int(row["Interval"]) != int(orig["Interval"])
                offs_changed = row["Offsets"] != orig["Offsets"]
                stat_changed = row["Status"] != orig["Status"]
                
                if due_dt_changed or freq_changed or int_changed or offs_changed or stat_changed:
                    db_rem = db.query(Reminder).filter(Reminder.id == r_id).first()
                    if db_rem:
                        db_rem.current_due_date = datetime.strptime(str(row["Next Due Date"]), "%Y-%m-%d")
                        db_rem.frequency = row["Frequency"]
                        db_rem.recurrence_interval = int(row["Interval"])
                        db_rem.reminder_offsets = row["Offsets"]
                        db_rem.status = row["Status"]
                        db.commit()
                        st.toast(f"Updated Reminder ID {r_id}!", icon="✅")
                        st.rerun()
                        
            # Create Reminder manually
            st.markdown("---")
            st.markdown("### ➕ Map New Client Reminder Schedule")
            with st.form("new_reminder_form"):
                clients = db.query(Client).all()
                client_opts = {f"{c.business_name} ({c.email or 'No email'})": c.id for c in clients}
                sel_client_name = st.selectbox("Select Client Business*", list(client_opts.keys()))
                
                types = db.query(ReminderType).all()
                type_opts = {t.name: t.id for t in types}
                sel_type_name = st.selectbox("Filing / Reminder Type*", list(type_opts.keys()))
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    first_due = st.date_input("First Obligation Due Date*", value=datetime.today() + timedelta(days=30))
                    freq = st.selectbox("Recurrence Frequency*", ["One Time", "Monthly", "Quarterly", "Annually", "Custom"])
                    rec_int = st.number_input("Recurrence Interval Multiplier", min_value=1, value=1, step=1)
                with col_d2:
                    selected_t_obj = db.query(ReminderType).filter(ReminderType.name == sel_type_name).first()
                    default_offs = selected_t_obj.default_days_before if selected_t_obj else "30,14,7,2"
                    offsets_str = st.text_input("Days Before Reminder (Offsets, comma separated)*", value=default_offs)
                    
                    templates = db.query(EmailTemplate).all()
                    tmpl_opts = {"Default Type Template": 0}
                    for tmpl in templates:
                        tmpl_opts[tmpl.name] = tmpl.id
                    sel_tmpl_name = st.selectbox("Custom Email Template (Optional)", list(tmpl_opts.keys()))
                
                custom_days = st.number_input("Custom Interval Days (For 'Custom' frequency only)", min_value=0, value=0)
                notes = st.text_area("Filing notes / staff signature instructions")
                
                submit_rem = st.form_submit_button("Register Reminder Schedule", type="primary")
                if submit_rem:
                    # Validations
                    client_id = client_opts[sel_client_name]
                    t_id = type_opts[sel_type_name]
                    c_obj = db.query(Client).filter(Client.id == client_id).first()
                    
                    if not c_obj or not c_obj.email:
                        st.error("Filing cannot be scheduled. This client does not have an email address configured.")
                    elif not offsets_str:
                        st.error("Filing offsets (e.g. 30,14,7,2) are required.")
                    else:
                        tmpl_id = tmpl_opts[sel_tmpl_name]
                        db_rem = Reminder(
                            client_id=client_id,
                            reminder_type_id=t_id,
                            first_due_date=datetime.combine(first_due, time.min),
                            current_due_date=datetime.combine(first_due, time.min),
                            frequency=freq,
                            recurrence_interval=int(rec_int),
                            reminder_offsets=offsets_str,
                            template_id=tmpl_id if tmpl_id > 0 else None,
                            status="ACTIVE",
                            custom_interval_days=custom_days if custom_days > 0 else None,
                            notes=notes
                        )
                        db.add(db_rem)
                        db.commit()
                        st.success("Successfully registered client reminder!")
                        st.rerun()
        else:
            st.dataframe(df_rems, use_container_width=True, hide_index=True)

def render_client_reminder_tab(db: Session, client: Client):
    """
    Renders the reminders configurations tab directly inside the client details profile.
    """
    st.subheader(f"⏰ Active Reminders for {client.business_name}")
    
    # Toggle Lock Check
    is_locked = client.status == "Locked"
    is_authorized = st.session_state.get("authenticated") and st.session_state.get("current_user_role") in ("Admin", "Accountant")
    
    reminders = db.query(Reminder).filter(Reminder.client_id == client.id).all()
    
    if not reminders:
        st.info("No active reminder schedules registered for this client.")
    else:
        records = []
        for r in reminders:
            records.append({
                "ID": r.id,
                "Filing Type": r.reminder_type.name if r.reminder_type else "Unknown",
                "Next Due Date": r.current_due_date.strftime("%Y-%m-%d"),
                "Frequency": r.frequency,
                "Offsets": r.reminder_offsets,
                "Status": r.status
            })
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
        
    if is_authorized and not is_locked:
        st.markdown("---")
        st.markdown("#### ➕ Add New Reminder for Client")
        with st.form(f"client_reminder_form_{client.id}"):
            types = db.query(ReminderType).all()
            type_opts = {t.name: t.id for t in types}
            sel_type_name = st.selectbox("Filing / Reminder Type*", list(type_opts.keys()))
            
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                first_due = st.date_input("First Obligation Due Date*", value=datetime.today() + timedelta(days=30))
                freq = st.selectbox("Recurrence Frequency*", ["One Time", "Monthly", "Quarterly", "Annually", "Custom"])
                rec_int = st.number_input("Recurrence Interval Multiplier", min_value=1, value=1, step=1)
            with col_r2:
                selected_t_obj = db.query(ReminderType).filter(ReminderType.name == sel_type_name).first()
                default_offs = selected_t_obj.default_days_before if selected_t_obj else "30,14,7,2"
                offsets_str = st.text_input("Days Before Reminder (Offsets, comma separated)*", value=default_offs)
                
                templates = db.query(EmailTemplate).all()
                tmpl_opts = {"Default Type Template": 0}
                for tmpl in templates:
                    tmpl_opts[tmpl.name] = tmpl.id
                sel_tmpl_name = st.selectbox("Custom Email Template (Optional)", list(tmpl_opts.keys()))
                
            custom_days = st.number_input("Custom Interval Days (For 'Custom' frequency only)", min_value=0, value=0)
            notes = st.text_area("Filing notes / staff signature instructions")
            
            submit_rem = st.form_submit_button("Register Reminder", type="primary")
            if submit_rem:
                if not client.email:
                    st.error("This client profile does not have an email address configured. Set client email first.")
                elif not offsets_str:
                    st.error("Offsets are required.")
                else:
                    tmpl_id = tmpl_opts[sel_tmpl_name]
                    db_rem = Reminder(
                        client_id=client.id,
                        reminder_type_id=type_opts[sel_type_name],
                        first_due_date=datetime.combine(first_due, time.min),
                        current_due_date=datetime.combine(first_due, time.min),
                        frequency=freq,
                        recurrence_interval=int(rec_int),
                        reminder_offsets=offsets_str,
                        template_id=tmpl_id if tmpl_id > 0 else None,
                        status="ACTIVE",
                        custom_interval_days=custom_days if custom_days > 0 else None,
                        notes=notes
                    )
                    db.add(db_rem)
                    db.commit()
                    st.success("Successfully registered reminder for this client!")
                    st.rerun()

def render_templates_tab(db: Session, is_authorized: bool):
    st.subheader("✉️ Email Templates Configuration")
    
    # List current templates
    templates = db.query(EmailTemplate).all()
    
    if not templates:
        st.info("No custom email templates loaded in the database yet.")
    else:
        tmpl_names = [t.name for t in templates]
        selected_tmpl_name = st.selectbox("Select Email Template to View/Edit", tmpl_names)
        tmpl_obj = next(t for t in templates if t.name == selected_tmpl_name)
        
        # Render Edit Form
        with st.form("edit_template_form"):
            subject = st.text_input("Email Subject Template", value=tmpl_obj.subject)
            body = st.text_area("Email HTML Body", value=tmpl_obj.body_html, height=250)
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                update_btn = st.form_submit_button("💾 Save Template Updates")
            with col_b2:
                # Preview simulation helper
                test_vars = {
                    "client_name": "Raman Demo Client",
                    "business_name": "Maple Tech Inc",
                    "period_start": "April 01, 2026",
                    "period_end": "June 30, 2026",
                    "due_date": "July 31, 2026",
                    "reminder_type": tmpl_obj.reminder_type.name if tmpl_obj.reminder_type else "Tax Obligation",
                    "staff_name": "Raman Accountant",
                    "company_name": "Maple Bookkeeping Services",
                    "phone": "604-555-0199",
                    "email": "beedhtaxservices@gmail.com"
                }
                
            if update_btn:
                if not is_authorized:
                    st.error("Access Denied: You do not have permissions to modify templates.")
                elif not subject or not body:
                    st.error("Subject and Body are required.")
                else:
                    tmpl_obj.subject = subject
                    tmpl_obj.body_html = body
                    db.commit()
                    st.success(f"Successfully updated template '{tmpl_obj.name}'!")
                    st.rerun()

        # Render preview outside form
        st.markdown("### 👁️ Rendered HTML Preview")
        try:
            preview_subject = parse_template(subject, test_vars)
            preview_body = parse_template(body, test_vars)
            
            st.markdown(f"**Subject Preview:** `{preview_subject}`")
            st.components.v1.html(preview_body, height=280, scrolling=True)
        except Exception as preview_err:
            st.error(f"Template rendering failed: {preview_err}")

    # Add custom template
    if is_authorized:
        st.markdown("---")
        st.markdown("### ➕ Create New Custom Email Template")
        with st.form("new_template_form"):
            new_name = st.text_input("Template Display Name*", placeholder="e.g. GST Early Alert Template")
            
            types = db.query(ReminderType).all()
            type_opts = {t.name: t.id for t in types}
            sel_type = st.selectbox("Associated Filing / Reminder Type", list(type_opts.keys()))
            
            new_subject = st.text_input("Subject Template*", placeholder="e.g. GST Alert - {{business_name}}")
            new_body = st.text_area("HTML Body Template*", placeholder="Hello {{client_name}},<br><br>GST is due {{due_date}}...")
            
            create_tmpl = st.form_submit_button("Register Template", type="primary")
            if create_tmpl:
                if not new_name or not new_subject or not new_body:
                    st.error("Template name, subject, and body are required fields.")
                else:
                    new_obj = EmailTemplate(
                        name=new_name,
                        reminder_type_id=type_opts[sel_type],
                        subject=new_subject,
                        body_html=new_body
                    )
                    db.add(new_obj)
                    db.commit()
                    st.success("Successfully registered new template!")
                    st.rerun()

def render_history_tab(db: Session):
    st.subheader("📜 Email Log History & Logs")
    
    # Export / Views
    histories = db.query(EmailHistory).order_by(EmailHistory.sent_at.desc()).all()
    
    if not histories:
        st.info("No outgoing email records logged in the database yet.")
    else:
        records = []
        for h in histories:
            records.append({
                "Date": h.sent_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "Recipient": h.recipient_email,
                "Subject": h.subject,
                "Filing Type": h.reminder_type_name or "N/A",
                "Status": h.status,
                "Message ID": h.gmail_message_id or "",
                "Error Details": h.error_message or ""
            })
            
        df_hist = pd.DataFrame(records)
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
        
        # Download options
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_data = df_hist.to_csv(index=False)
            st.download_button(
                label="📥 Download Log History as CSV",
                data=csv_data,
                file_name="reminder_email_history.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_dl2:
            # Excel export
            import io
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_hist.to_excel(writer, sheet_name="Email History", index=False)
            st.download_button(
                label="📊 Download Log History as Excel",
                data=buffer.getvalue(),
                file_name="reminder_email_history.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
    # Display Scheduler Execution Logs (Requirement 9)
    st.markdown("---")
    st.markdown("### ⚙️ Scheduler Run Log")
    runs = db.query(SchedulerRun).order_by(SchedulerRun.started_at.desc()).limit(15).all()
    if not runs:
        st.info("No scheduler execution runs documented yet.")
    else:
        run_records = []
        for r in runs:
            duration = ""
            if r.finished_at:
                diff = (r.finished_at - r.started_at).total_seconds()
                duration = f"{diff:.2f} sec"
                
            run_records.append({
                "Date (Started)": r.started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "Source": r.trigger_source,
                "Status": r.status,
                "Reminders Checked": r.reminders_checked,
                "Emails Sent": r.emails_sent,
                "Emails Failed": r.emails_failed,
                "Duration": duration,
                "Errors": r.error_summary or ""
            })
        st.dataframe(pd.DataFrame(run_records), use_container_width=True, hide_index=True)

def render_settings_tab(db: Session, is_authorized: bool):
    st.subheader("⚙️ Settings & Integration Setup")
    
    settings = db.query(ReminderSettings).first()
    
    # Display status
    if settings and settings.gmail_oauth_token:
        st.success(f"🟢 Gmail Account Connected: `{settings.gmail_authorized_email}`")
        status_label = "Authorized"
    else:
        st.warning("🔴 Gmail API: Disconnected (OAuth Refresh Token not found in database).")
        status_label = "Unauthorized"
        
    st.write("")
    
    if is_authorized:
        # Re-connection link generator
        st.markdown("#### Connection Setup")
        try:
            redirect_uri = st.secrets.get("GOOGLE_REDIRECT_URI", "http://localhost:8501/")
        except Exception:
            redirect_uri = "http://localhost:8501/"
            
        try:
            flow = get_oauth_flow(redirect_uri)
            auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
            
            st.markdown(
                f'<a href="{auth_url}" target="_self" style="display:inline-block; padding:0.6rem 1.2rem; background-color:#1e3d59; color:white; border-radius:6px; font-weight:600; text-decoration:none; margin-bottom:1rem;">🔄 Connect / Reconnect Gmail Account</a>',
                unsafe_allow_html=True
            )
        except Exception as flow_err:
            st.error(f"Cannot generate Google OAuth link: {flow_err}")
            
        # Send Test Email
        st.markdown("---")
        st.markdown("#### 🧪 Dispatch Test Email")
        test_email_addr = st.text_input("Send a test email to:", value=settings.gmail_authorized_email if settings else "")
        test_btn = st.button("🚀 Send Test Email Now")
        
        if test_btn:
            if not test_email_addr or "@" not in test_email_addr:
                st.error("Provide a valid email address.")
            elif not settings or not settings.gmail_oauth_token:
                st.error("Gmail is not connected yet. Connect your Gmail account first.")
            else:
                with st.spinner("Dispatching test email..."):
                    try:
                        service, refreshed = get_gmail_service(settings.gmail_oauth_token)
                        if refreshed != settings.gmail_oauth_token:
                            settings.gmail_oauth_token = refreshed
                            db.commit()
                            
                        # Send
                        msg_id = send_gmail_email(
                            service=service,
                            to_email=test_email_addr,
                            subject="Maple Bookkeeping - Gmail Integration Connection Test",
                            body_html="<h3>Connection Successful!</h3><p>This test email confirms that Maple Bookkeeping is fully authorized to send reminders from your connected Gmail account.</p>"
                        )
                        st.success(f"Test email successfully dispatched! Message ID: `{msg_id}`")
                    except Exception as test_err:
                        st.error(f"Test email dispatch failed: {test_err}")
                        
        # Manual Scheduler trigger
        st.markdown("---")
        st.markdown("#### 🔄 Trigger Daily Scheduler Run")
        st.write("Clicking this button runs a single cycle of the Daily Reminder Scheduler. It checks all active reminders, calculates which notifications are due, and sends the emails immediately.")
        run_btn = st.button("🏃 Run Scheduler Check Now")
        if run_btn:
            with st.spinner("Processing daily reminder check..."):
                try:
                    res = run_scheduler_cycle(trigger_source="MANUAL")
                    status_symbol = "🟢" if res["status"] == "SUCCESS" else "🔴"
                    st.success(
                        f"Scheduler cycle finished! Status: {status_symbol} {res['status']} | "
                        f"Checked: {res['reminders_checked']} | Sent: {res['emails_sent']} | Failed: {res['emails_failed']}"
                    )
                    if res["errors"]:
                        st.warning("Warnings/Errors occurred:")
                        for err in res["errors"]:
                            st.write(f"- {err}")
                except Exception as run_err:
                    st.error(f"Scheduler run failed: {run_err}")
    else:
        st.info("Log in with an Admin or Accountant account to adjust integrations or send tests.")
