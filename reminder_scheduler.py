import sys
from services.reminder_scheduler import run_scheduler_cycle

if __name__ == "__main__":
    print("[Scheduler Standalone] Initiating Daily Reminder Cycle...")
    res = run_scheduler_cycle(trigger_source="AUTO")
    print(f"[Scheduler Standalone] Complete. Status: {res['status']}, Checked: {res['reminders_checked']}, Sent: {res['emails_sent']}, Failed: {res['emails_failed']}")
    if res["errors"]:
        print("Encountered Warnings/Errors:")
        for err in res["errors"]:
            print(f"  - {err}")
    if res["status"] == "FAILED":
        sys.exit(1)
