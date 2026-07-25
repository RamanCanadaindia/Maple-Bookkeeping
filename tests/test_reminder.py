import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, time, timedelta
import pytz
from services.reminder_scheduler import advance_due_date, get_period_dates, calculate_send_datetime_utc
from services.gmail_service import parse_template

def test_offset_date_calculations():
    # Due on Oct 15, send offset 30 days -> should resolve to Sept 15
    due_date = datetime(2026, 10, 15, 0, 0)
    send_date_utc = calculate_send_datetime_utc(due_date, 30)
    
    # In Vancouver timezone, target is Sept 15 at 9:00 AM
    vancouver_tz = pytz.timezone("America/Vancouver")
    local_dt = send_date_utc.astimezone(vancouver_tz)
    
    assert local_dt.date().month == 9
    assert local_dt.date().day == 15
    assert local_dt.time().hour == 9

def test_recurrence_advancement():
    # Monthly end-of-month clamp (non-leap year)
    # Jan 31 -> Feb 28
    d1 = datetime(2026, 1, 31, 0, 0)
    d2 = advance_due_date(d1, "Monthly")
    assert d2.month == 2
    assert d2.day == 28

    # Monthly end-of-month clamp (leap year)
    # Jan 31 -> Feb 29
    d_leap = datetime(2028, 1, 31, 0, 0)
    d_leap_2 = advance_due_date(d_leap, "Monthly")
    assert d_leap_2.month == 2
    assert d_leap_2.day == 29

    # Quarterly end-of-month check
    # March 31 -> June 30
    dq1 = datetime(2026, 3, 31, 0, 0)
    dq2 = advance_due_date(dq1, "Quarterly")
    assert dq2.month == 6
    assert dq2.day == 30

    # Annually check
    # Dec 31, 2025 -> Dec 31, 2026
    dy1 = datetime(2025, 12, 31, 0, 0)
    dy2 = advance_due_date(dy1, "Annually")
    assert dy2.year == 2026
    assert dy2.month == 12
    assert dy2.day == 31

def test_template_substitution():
    tmpl = "Hello {{client_name}}, your {{reminder_type}} is due on {{due_date}}."
    vars_dict = {
        "client_name": "Raman Business Services",
        "reminder_type": "GST Return",
        "due_date": "July 31, 2026",
    }
    res = parse_template(tmpl, vars_dict)
    assert res == "Hello Raman Business Services, your GST Return is due on July 31, 2026."

def test_missing_template_variable():
    tmpl = "Hello {{client_name}}, your {{reminder_type}} is due on {{due_date}}."
    vars_dict = {
        "client_name": "Raman",
    }
    try:
        parse_template(tmpl, vars_dict)
        assert False, "Expected ValueError but none was raised"
    except ValueError:
        pass

def test_period_separation():
    # Due Date: July 31, 2026
    due_date = datetime(2026, 7, 31, 0, 0)
    
    # Monthly period: June 01 to June 30
    start_m, end_m = get_period_dates(due_date, "Monthly")
    assert start_m.date().strftime("%Y-%m-%d") == "2026-06-01"
    assert end_m.date().strftime("%Y-%m-%d") == "2026-06-30"

    # Quarterly period: April 01 to June 30
    start_q, end_q = get_period_dates(due_date, "Quarterly")
    assert start_q.date().strftime("%Y-%m-%d") == "2026-04-01"
    assert end_q.date().strftime("%Y-%m-%d") == "2026-06-30"

if __name__ == "__main__":
    print("[Testing] Running unit tests...")
    test_offset_date_calculations()
    test_recurrence_advancement()
    test_template_substitution()
    
    try:
        test_missing_template_variable()
    except ValueError:
        pass # Expected
        
    test_period_separation()
    print("[Testing] All unit tests completed successfully!")
