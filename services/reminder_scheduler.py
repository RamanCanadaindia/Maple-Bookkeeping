import os
import sys
import calendar
import traceback
from datetime import datetime, timedelta, time
import pytz
from sqlalchemy.orm import Session

# Add project path to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import Reminder, ReminderType, Notification, EmailTemplate, EmailHistory, ReminderSettings, SchedulerRun, Client
from services.gmail_service import get_gmail_service, send_gmail_email, parse_template

def send_email_via_provider(db: Session, to_email: str, subject: str, body_html: str) -> str:
    """
    Sends an email using the active configured email service provider (GMAIL or RESEND).
    Returns the message ID/identifier.
    """
    import requests
    import json
    
    settings = db.query(ReminderSettings).first()
    if not settings:
        raise ValueError("System settings are not initialized.")
        
    provider = getattr(settings, "email_service_provider", "GMAIL")
    if provider == "RESEND":
        resend_api_key_encrypted = getattr(settings, "resend_api_key", None)
        if not resend_api_key_encrypted:
            raise ValueError("Resend API Key is not configured in Settings.")
            
        # Decrypt key
        from services.gmail_service import decrypt_token
        resend_api_key = decrypt_token(resend_api_key_encrypted)
        
        from_email = getattr(settings, "resend_from_email", None)
        if not from_email or not from_email.strip():
            from_email = "onboarding@resend.dev"
            
        headers = {
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": body_html
        }
        
        response = requests.post("https://api.resend.com/emails", json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Resend API error: {response.text}")
            
        res_data = response.json()
        return res_data.get("id", "resend_sent")
        
    else: # GMAIL
        if not settings.gmail_oauth_token:
            raise ValueError("Gmail account is not connected. Connect in Settings first.")
            
        gmail_service, refreshed_token = get_gmail_service(settings.gmail_oauth_token)
        if refreshed_token != settings.gmail_oauth_token:
            settings.gmail_oauth_token = refreshed_token
            db.commit()
            
        msg_id = send_gmail_email(
            service=gmail_service,
            to_email=to_email,
            subject=subject,
            body_html=body_html
        )
        return msg_id

def add_months(source_date: datetime, months: int) -> datetime:
    """
    Standard library calendar-aware addition of months.
    """
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, source_date.hour, source_date.minute, source_date.second)

def advance_due_date(current_date: datetime, frequency: str, recurrence_interval: int = 1, day_of_month: int = None, month_of_year: int = None, custom_interval_days: int = None) -> datetime:
    """
    Advances the current due date to the next period.
    Preserves end-of-month alignments where appropriate.
    """
    if frequency == "One Time":
        return None
        
    last_day = calendar.monthrange(current_date.year, current_date.month)[1]
    is_eom = (current_date.day == last_day)
    
    if frequency == "Monthly":
        next_date = add_months(current_date, recurrence_interval)
    elif frequency == "Quarterly":
        next_date = add_months(current_date, 3 * recurrence_interval)
    elif frequency == "Annually":
        next_date = add_months(current_date, 12 * recurrence_interval)
    elif frequency == "Custom":
        if custom_interval_days:
            next_date = current_date + timedelta(days=custom_interval_days)
        else:
            next_date = add_months(current_date, recurrence_interval)
    else:
        next_date = add_months(current_date, 1)
        
    # EOM adjustment
    if is_eom and frequency in ("Monthly", "Quarterly", "Annually"):
        new_last_day = calendar.monthrange(next_date.year, next_date.month)[1]
        next_date = next_date.replace(day=new_last_day)
        
    # Preserving day_of_month / month_of_year
    if day_of_month is not None and frequency in ("Monthly", "Quarterly", "Annually"):
        max_day = calendar.monthrange(next_date.year, next_date.month)[1]
        next_date = next_date.replace(day=min(day_of_month, max_day))
        
    if month_of_year is not None and frequency == "Annually":
        next_date = next_date.replace(month=month_of_year)
        max_day = calendar.monthrange(next_date.year, next_date.month)[1]
        next_date = next_date.replace(day=min(next_date.day, max_day))
        
    return next_date

def get_period_dates(current_due_date: datetime, frequency: str):
    """
    Determines filing period start and end dates based on due date.
    GST and Corporate tax filings generally cover the period preceding the due date.
    """
    if frequency == "Monthly":
        # Period is the preceding month
        end_date = add_months(current_due_date, -1)
        last_day = calendar.monthrange(end_date.year, end_date.month)[1]
        end_date = end_date.replace(day=last_day)
        start_date = end_date.replace(day=1)
    elif frequency == "Quarterly":
        # Period is the preceding quarter (3 months)
        end_date = add_months(current_due_date, -1)
        last_day = calendar.monthrange(end_date.year, end_date.month)[1]
        end_date = end_date.replace(day=last_day)
        start_date = add_months(end_date, -2).replace(day=1)
    elif frequency == "Annually":
        # Period is the preceding fiscal year (12 months)
        end_date = add_months(current_due_date, -1)
        last_day = calendar.monthrange(end_date.year, end_date.month)[1]
        end_date = end_date.replace(day=last_day)
        start_date = add_months(end_date, -11).replace(day=1)
    else:
        start_date = current_due_date
        end_date = current_due_date
    return start_date, end_date

def calculate_send_datetime_utc(due_date_vancouver: datetime, offset_days: int) -> datetime:
    """
    Calculates the scheduled send timestamp (9:00 AM Vancouver time) in UTC.
    """
    send_date = due_date_vancouver.date() - timedelta(days=offset_days)
    vancouver_tz = pytz.timezone("America/Vancouver")
    local_dt = vancouver_tz.localize(datetime.combine(send_date, time(9, 0)))
    return local_dt.astimezone(pytz.utc)

def seed_initial_data(db: Session):
    """
    Seeds initial reminder types and templates if they do not exist.
    """
    initial_types = [
        {"name": "GST Return", "code": "gst_return", "default_days_before": "30,14,7,2"},
        {"name": "Corporate Tax Filing", "code": "corporate_tax_filing", "default_days_before": "60,30,14,7"},
        {"name": "Corporate Tax Balance", "code": "corporate_tax_balance", "default_days_before": "60,30,14,7"},
        {"name": "Payroll Remittance", "code": "payroll_remittance", "default_days_before": "7,3,1"},
        {"name": "Annual Report", "code": "annual_report", "default_days_before": "30,14,7"}
    ]
    
    type_map = {}
    for t_data in initial_types:
        t = db.query(ReminderType).filter(ReminderType.code == t_data["code"]).first()
        if not t:
            t = ReminderType(
                name=t_data["name"],
                code=t_data["code"],
                default_days_before=t_data["default_days_before"],
                is_custom=False
            )
            db.add(t)
            db.commit()
            db.refresh(t)
        type_map[t_data["code"]] = t.id

    # Seed default templates
    default_templates = [
        {
            "code": "gst_return",
            "name": "Default GST Return Template",
            "subject": "GST Return Filing Reminder - {{business_name}}",
            "body": "Hello {{client_name}},<br><br>This is a reminder that your GST Return for the period {{period_start}} to {{period_end}} is due on {{due_date}}.<br><br>Please send us your bookkeeping files as soon as possible.<br><br>Best regards,<br>{{staff_name}}<br>{{company_name}}"
        },
        {
            "code": "corporate_tax_filing",
            "name": "Default T2 Filing Template",
            "subject": "T2 Corporate Tax Filing Reminder - {{business_name}}",
            "body": "Hello {{client_name}},<br><br>This is a reminder that your T2 Corporate Tax Return for the fiscal period {{period_start}} to {{period_end}} is due for filing on {{due_date}}.<br><br>Best regards,<br>{{staff_name}}<br>{{company_name}}"
        },
        {
            "code": "corporate_tax_balance",
            "name": "Default Corporate Balance Template",
            "subject": "Corporate Tax Balance Payment Due - {{business_name}}",
            "body": "Hello {{client_name}},<br><br>This is a reminder that your Corporate Tax Balance / Payment for the period ending {{period_end}} is due to the CRA on {{due_date}}.<br><br>Best regards,<br>{{staff_name}}<br>{{company_name}}"
        },
        {
            "code": "payroll_remittance",
            "name": "Default Payroll Remittance Template",
            "subject": "Payroll Remittance Due - {{business_name}}",
            "body": "Hello {{client_name}},<br><br>This is a reminder that your Payroll Remittance for the period ending {{period_end}} is due to the CRA on {{due_date}}.<br><br>Best regards,<br>{{staff_name}}<br>{{company_name}}"
        },
        {
            "code": "annual_report",
            "name": "Default Annual Report Template",
            "subject": "Annual Report Filing Reminder - {{business_name}}",
            "body": "Hello {{client_name}},<br><br>This is a reminder that your Corporate Annual Report for {{due_date}} is due for filing.<br><br>Best regards,<br>{{staff_name}}<br>{{company_name}}"
        }
    ]

    for tmpl in default_templates:
        existing = db.query(EmailTemplate).filter(
            EmailTemplate.reminder_type_id == type_map[tmpl["code"]],
            EmailTemplate.name == tmpl["name"]
        ).first()
        if not existing:
            t_obj = EmailTemplate(
                reminder_type_id=type_map[tmpl["code"]],
                name=tmpl["name"],
                subject=tmpl["subject"],
                body_html=tmpl["body"]
            )
            db.add(t_obj)
            db.commit()

def run_scheduler_cycle(trigger_source: str = "AUTO") -> dict:
    """
    Executes one complete daily scheduler run cycle.
    """
    db = SessionLocal()
    started_at = datetime.utcnow()
    run_log = SchedulerRun(
        started_at=started_at,
        status="RUNNING",
        trigger_source=trigger_source
    )
    db.add(run_log)
    db.commit()
    db.refresh(run_log)

    checked = 0
    sent = 0
    failed = 0
    errors = []

    try:
        # 1. Seed default types/templates
        seed_initial_data(db)

        # 2. Check active provider and setup if GMAIL
        gmail_settings = db.query(ReminderSettings).first()
        gmail_service = None
        provider = getattr(gmail_settings, "email_service_provider", "GMAIL") if gmail_settings else "GMAIL"
        
        if provider == "GMAIL" and gmail_settings and gmail_settings.gmail_oauth_token:
            try:
                gmail_service, refreshed_token = get_gmail_service(gmail_settings.gmail_oauth_token)
                if refreshed_token != gmail_settings.gmail_oauth_token:
                    gmail_settings.gmail_oauth_token = refreshed_token
                    db.commit()
            except Exception as oauth_err:
                errors.append(f"OAuth Initialization failed: {oauth_err}")

        # 3. Process active reminders
        active_reminders = db.query(Reminder).filter(Reminder.status == "ACTIVE").all()
        
        vancouver_tz = pytz.timezone("America/Vancouver")
        now_utc = datetime.utcnow()
        now_vancouver = datetime.now(pytz.utc).astimezone(vancouver_tz)
        vancouver_date = now_vancouver.date()

        for rem in active_reminders:
            checked += 1
            client = rem.client
            if not client:
                continue

            # Ensure client email is present
            client_email = client.email
            if not client_email:
                # Flag notification failed due to missing client email
                errors.append(f"Reminder ID {rem.id}: Client business '{client.business_name}' has no email defined.")
                continue

            # Load active template
            template = rem.template
            if not template and rem.reminder_type_id:
                # Load default template for this type
                template = db.query(EmailTemplate).filter(EmailTemplate.reminder_type_id == rem.reminder_type_id).first()
            
            if not template:
                errors.append(f"Reminder ID {rem.id}: No email template linked or default template found.")
                continue

            # Check if notifications for current_due_date are initialized
            offsets = [int(o.strip()) for o in rem.reminder_offsets.split(",") if o.strip().isdigit()]
            
            for offset in offsets:
                # Calculate scheduled send date in UTC
                sched_date_utc = calculate_send_datetime_utc(rem.current_due_date, offset)
                
                # Try to insert Notification (unique constraint checks identity)
                try:
                    # Identity: reminder_id, current_due_date, offset_days, recipient_email, template_id, channel
                    notif = db.query(Notification).filter(
                        Notification.reminder_id == rem.id,
                        Notification.current_due_date == rem.current_due_date,
                        Notification.offset_days == offset,
                        Notification.recipient_email == client_email,
                        Notification.template_id == template.id,
                        Notification.channel == "GMAIL"
                    ).first()
                    
                    if not notif:
                        notif = Notification(
                            reminder_id=rem.id,
                            current_due_date=rem.current_due_date,
                            offset_days=offset,
                            recipient_email=client_email,
                            template_id=template.id,
                            channel="GMAIL",
                            status="PENDING",
                            scheduled_send_date=sched_date_utc
                        )
                        db.add(notif)
                        db.commit()
                except Exception as db_err:
                    db.rollback()

            # Process pending/failed notifications for this reminder due today
            notifications_to_send = db.query(Notification).filter(
                Notification.reminder_id == rem.id,
                Notification.current_due_date == rem.current_due_date,
                Notification.status.in_(["PENDING", "FAILED"]),
                Notification.scheduled_send_date <= now_utc
            ).all()

            for notif in notifications_to_send:
                # Transactional Row Lock (Duplicate-Send Protection)
                try:
                    # Select with lock
                    locked_notif = db.query(Notification).filter(
                        Notification.id == notif.id,
                        Notification.status.in_(["PENDING", "FAILED"])
                    ).with_for_update().first()
                    
                    if not locked_notif:
                        continue
                        
                    locked_notif.status = "PROCESSING"
                    locked_notif.processing_started_at = datetime.utcnow()
                    db.commit()
                except Exception as lock_err:
                    db.rollback()
                    errors.append(f"Failed to claim notification ID {notif.id}: {lock_err}")
                    continue

                # Prepare template variables
                period_start, period_end = get_period_dates(rem.current_due_date, rem.frequency)
                
                vars_dict = {
                    "client_name": client.business_name,
                    "business_name": client.business_name,
                    "period_start": period_start.strftime("%B %d, %Y"),
                    "period_end": period_end.strftime("%B %d, %Y"),
                    "due_date": rem.current_due_date.strftime("%B %d, %Y"),
                    "reminder_type": rem.reminder_type.name if rem.reminder_type else "Tax Filing",
                    "staff_name": rem.notes or "Your Accountant",  # fallback or assigned staff notes
                    "company_name": "Maple Bookkeeping",
                    "phone": "604-555-0199",
                    "email": client_email
                }

                # Attempt Email Dispatch
                try:
                    # Parse template variables (raises error if missing)
                    parsed_subject = parse_template(template.subject, vars_dict)
                    parsed_body = parse_template(template.body_html, vars_dict)

                    # Send email via active provider
                    msg_id = send_email_via_provider(
                        db=db,
                        to_email=client_email,
                        subject=parsed_subject,
                        body_html=parsed_body
                    )

                    # Update Notification State to SENT
                    locked_notif.status = "SENT"
                    locked_notif.sent_at = datetime.utcnow()
                    locked_notif.attempt_count += 1
                    locked_notif.gmail_message_id = msg_id
                    db.commit()

                    # Audit to Email History
                    history = EmailHistory(
                        reminder_id=rem.id,
                        sent_at=datetime.utcnow(),
                        recipient_email=client_email,
                        subject=parsed_subject,
                        reminder_type_name=rem.reminder_type.name if rem.reminder_type else None,
                        status="SENT",
                        gmail_message_id=msg_id
                    )
                    db.add(history)
                    db.commit()
                    sent += 1

                except Exception as send_err:
                    db.rollback()
                    # Update state to FAILED
                    locked_notif.status = "FAILED"
                    locked_notif.attempt_count += 1
                    locked_notif.last_error = str(send_err)
                    db.commit()

                    # Audit Failed Email History
                    history = EmailHistory(
                        reminder_id=rem.id,
                        sent_at=datetime.utcnow(),
                        recipient_email=client_email,
                        subject=template.subject,
                        reminder_type_name=rem.reminder_type.name if rem.reminder_type else None,
                        status="FAILED",
                        error_message=str(send_err)
                    )
                    db.add(history)
                    db.commit()

                    failed += 1
                    errors.append(f"Failed sending Notification ID {notif.id}: {send_err}")

            # Check if all notifications for current due date are finished
            pending_or_processing = db.query(Notification).filter(
                Notification.reminder_id == rem.id,
                Notification.current_due_date == rem.current_due_date,
                Notification.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if pending_or_processing == 0:
                # All offset dispatches are processed. Advance current due date to next recurrence
                next_due = advance_due_date(
                    current_date=rem.current_due_date,
                    frequency=rem.frequency,
                    recurrence_interval=rem.recurrence_interval,
                    day_of_month=rem.day_of_month,
                    month_of_year=rem.month_of_year,
                    custom_interval_days=rem.custom_interval_days
                )
                if next_due:
                    rem.current_due_date = next_due
                    db.commit()
                else:
                    # One Time reminder is finished, set status to PAUSED (or completed/paused)
                    rem.status = "PAUSED"
                    db.commit()

        # Update run log status
        run_log.status = "SUCCESS"
        run_log.finished_at = datetime.utcnow()
        run_log.reminders_checked = checked
        run_log.emails_sent = sent
        run_log.emails_failed = failed
        db.commit()

    except Exception as general_err:
        db.rollback()
        error_msg = f"Fatal Scheduler Error:\n{traceback.format_exc()}"
        errors.append(error_msg)
        run_log.status = "FAILED"
        run_log.finished_at = datetime.utcnow()
        run_log.error_summary = "; ".join(errors)[:1000]
        db.commit()

    db.close()
    return {
        "status": run_log.status,
        "reminders_checked": checked,
        "emails_sent": sent,
        "emails_failed": failed,
        "errors": errors
    }

def dispatch_notification_manually(db: Session, notif_id: int) -> tuple[bool, str]:
    """
    Forces the direct immediate sending of a scheduled Notification, regardless of date/offset.
    Returns (success, message).
    """
    from services.gmail_service import get_gmail_service, send_gmail_email, parse_template
    from datetime import datetime
    
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif:
        return False, "Notification not found."
        
    rem = notif.reminder
    if not rem:
        return False, "Linked reminder configuration not found."
        
    client = rem.client
    if not client or not client.email:
        return False, "Client email is not configured."
        
    # Check settings connection
    gmail_settings = db.query(ReminderSettings).first()
    if not gmail_settings:
        return False, "Reminder settings not configured."
        
    provider = getattr(gmail_settings, "email_service_provider", "GMAIL")
    if provider == "GMAIL" and not gmail_settings.gmail_oauth_token:
        return False, "Gmail integration is not authorized in Settings."
    elif provider == "RESEND" and not getattr(gmail_settings, "resend_api_key", None):
        return False, "Resend API Key is not configured in Settings."
        
    # Build vars
    period_start, period_end = get_period_dates(rem.current_due_date, rem.frequency)
    vars_dict = {
        "client_name": client.business_name,
        "business_name": client.business_name,
        "period_start": period_start.strftime("%B %d, %Y"),
        "period_end": period_end.strftime("%B %d, %Y"),
        "due_date": rem.current_due_date.strftime("%B %d, %Y"),
        "reminder_type": rem.reminder_type.name if rem.reminder_type else "Tax Filing",
        "staff_name": rem.notes or "Your Accountant",
        "company_name": "Maple Bookkeeping",
        "phone": "604-555-0199",
        "email": client.email
    }
    
    try:
        subject = parse_template(notif.template.subject, vars_dict)
        body = parse_template(notif.template.body, vars_dict)
        
        # Send
        msg_id = send_email_via_provider(db, to_email=client.email, subject=subject, body_html=body)
        
        # Mark SENT
        notif.status = "SENT"
        notif.sent_at = datetime.utcnow()
        notif.processing_started_at = datetime.utcnow()
        
        # Write to EmailHistory
        from core.models import EmailHistory
        hist = EmailHistory(
            notification_id=notif.id,
            recipient_email=client.email,
            subject=subject,
            sent_at=datetime.utcnow(),
            status="SUCCESS",
            message_id=msg_id
        )
        db.add(hist)
        db.commit()
        return True, f"Successfully sent to {client.email}! Message ID: {msg_id}"
    except Exception as send_err:
        db.rollback()
        # Mark FAILED
        notif.status = "FAILED"
        notif.sent_at = datetime.utcnow()
        from core.models import EmailHistory
        hist = EmailHistory(
            notification_id=notif.id,
            recipient_email=client.email,
            subject=notif.template.subject,
            sent_at=datetime.utcnow(),
            status="FAILED",
            error_details=str(send_err)
        )
        db.add(hist)
        db.commit()
        return False, f"Failed to send: {send_err}"

def dispatch_reminder_test_email(db: Session, reminder_id: int) -> tuple[bool, str]:
    """
    Triggers an immediate test email send for a given Reminder configuration.
    """
    from services.gmail_service import get_gmail_service, send_gmail_email, parse_template
    from datetime import datetime
    from core.models import EmailHistory, Reminder, EmailTemplate, ReminderSettings
    
    rem = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not rem:
        return False, "Reminder configuration not found."
        
    client = rem.client
    if not client or not client.email:
        return False, "Client email is not configured."
        
    # Load template
    template = rem.template
    if not template and rem.reminder_type_id:
        template = db.query(EmailTemplate).filter(EmailTemplate.reminder_type_id == rem.reminder_type_id).first()
    if not template:
        return False, "No email template found for this reminder."
        
    # Check settings connection
    gmail_settings = db.query(ReminderSettings).first()
    if not gmail_settings:
        return False, "Reminder settings not configured."
        
    provider = getattr(gmail_settings, "email_service_provider", "GMAIL")
    if provider == "GMAIL" and not gmail_settings.gmail_oauth_token:
        return False, "Gmail integration is not authorized in Settings."
    elif provider == "RESEND" and not getattr(gmail_settings, "resend_api_key", None):
        return False, "Resend API Key is not configured in Settings."
        
    # Build vars
    period_start, period_end = get_period_dates(rem.current_due_date, rem.frequency)
    vars_dict = {
        "client_name": client.business_name,
        "business_name": client.business_name,
        "period_start": period_start.strftime("%B %d, %Y"),
        "period_end": period_end.strftime("%B %d, %Y"),
        "due_date": rem.current_due_date.strftime("%B %d, %Y"),
        "reminder_type": rem.reminder_type.name if rem.reminder_type else "Tax Filing",
        "staff_name": rem.notes or "Your Accountant",
        "company_name": "Maple Bookkeeping",
        "phone": "604-555-0199",
        "email": client.email
    }
    
    try:
        subject = parse_template(template.subject, vars_dict)
        body = parse_template(template.body, vars_dict)
        
        # Send
        msg_id = send_email_via_provider(db, to_email=client.email, subject=subject, body_html=body)
        
        # Write to EmailHistory
        hist = EmailHistory(
            recipient_email=client.email,
            subject=subject,
            sent_at=datetime.utcnow(),
            status="SUCCESS",
            message_id=msg_id
        )
        db.add(hist)
        db.commit()
        return True, f"Successfully sent test reminder to {client.email}! Message ID: {msg_id}"
    except Exception as send_err:
        db.rollback()
        # Write to EmailHistory as FAILED
        hist = EmailHistory(
            recipient_email=client.email,
            subject=template.subject,
            sent_at=datetime.utcnow(),
            status="FAILED",
            error_details=str(send_err)
        )
        db.add(hist)
        db.commit()
        return False, f"Failed to send: {send_err}"

if __name__ == "__main__":
    # If run standalone, execute scheduler cycle
    print("[Scheduler] Starting Daily Reminder Processing Cycle...")
    res = run_scheduler_cycle(trigger_source="AUTO")
    print(f"[Scheduler] Cycle Finished. Status: {res['status']}, Checked: {res['reminders_checked']}, Sent: {res['emails_sent']}, Failed: {res['emails_failed']}")
    if res["errors"]:
        print(f"[Scheduler] Warnings/Errors encountered during run:")
        for err in res["errors"]:
            print(f"  - {err}")
        # Return failure exit code if fatal error occurred
        if res["status"] == "FAILED":
            sys.exit(1)
