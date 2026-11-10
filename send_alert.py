"""Email a short alert when the daily report fails or a trading day goes unreported.
usage: python send_alert.py "<message>" "<run url>" """
import os, smtplib, sys
from email.message import EmailMessage

message = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else \
    "A step in today's run failed before the report could be sent."
run_url = sys.argv[2] if len(sys.argv) > 2 else ""
user = os.environ["GMAIL_USER"]; to = os.environ.get("REPORT_TO") or user

msg = EmailMessage()
msg["Subject"] = "Daily Stock Focus: report not sent"
msg["From"] = user; msg["To"] = to
msg.set_content(f"{message}\n\nRun details: {run_url}\n\n"
                "Forward this email (or the run link) to Claude to get it fixed.")
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(user, os.environ["GMAIL_APP_PASSWORD"])
    s.send_message(msg)
print("Alert emailed.")
