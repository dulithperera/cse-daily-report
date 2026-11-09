"""Email the day's PDF via Gmail. Needs GMAIL_USER and GMAIL_APP_PASSWORD (GitHub secrets); REPORT_TO is optional."""
import json, os, smtplib, sys
from email.message import EmailMessage

pdf, day_path = sys.argv[1], sys.argv[2]
day = json.load(open(day_path)); m = day["market"]
user = os.environ["GMAIL_USER"]; to = os.environ.get("REPORT_TO") or user


def f(v, d=2):
    return "–" if v is None else f"{v:,.{d}f}"

nf = None
if m.get("foreign_buy_mn") is not None and m.get("foreign_sell_mn") is not None:
    nf = m["foreign_buy_mn"] - m["foreign_sell_mn"]
moves = [(t, (q["close"] / q["prev_close"] - 1) * 100) for t, q in day["prices"].items() if q.get("prev_close")]
moves.sort(key=lambda x: x[1])
lines = [
    f"ASPI {f(m.get('aspi'))} · S&P SL20 {f(m.get('sl20'))}",
    f"Turnover LKR {f(m.get('turnover_mn'))} mn · Net foreign LKR {f(nf)} mn",
    f"Breadth: {m.get('gainers')} up, {m.get('losers')} down, {m.get('unchanged')} unchanged",
]
if moves:
    lines.append(f"Top covered gainer: {moves[-1][0]} {moves[-1][1]:+.2f}% · Top loser: {moves[0][0]} {moves[0][1]:+.2f}%")
if not day.get("dailySummaryReady"):
    lines.append("CSE had not yet published the day's foreign flows, market cap and PE/PBV, so those show as –.")

msg = EmailMessage()
msg["Subject"] = f"Daily Stock Focus · {day['date']}"
msg["From"] = user; msg["To"] = to
msg.set_content("\n".join(lines) + "\n\nFull report attached. For information only, not investment advice.")
msg.add_attachment(open(pdf, "rb").read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf))
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(user, os.environ["GMAIL_APP_PASSWORD"])
    s.send_message(msg)
print("Report emailed.")
