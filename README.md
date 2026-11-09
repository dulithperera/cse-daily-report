# CSE Daily Stock Focus

A PDF report on the Colombo Stock Exchange, built by GitHub Actions at 4:45 PM Colombo time on weekdays and emailed to you. Days with no trading (Poya days, holidays) are skipped without sending anything.

## Files
- `collect_cse.py`: pulls the day's indices, sector indices, prices, turnover and foreign flows from cse.lk.
- `build_report.py` + `report.css`: renders the PDF.
- `send_email.py`: emails it via Gmail.
- `baseline.json`: company earnings, shares, book value and dividends from the latest published company results (snapshot as of 6 Nov 2026). Refresh it when companies publish new results.
- `history.json`: running record of daily closes, updated by each run.
- `reports/`: every PDF built.

## Secrets (Settings → Secrets and variables → Actions)
- `GMAIL_USER`: the Gmail address that sends the report.
- `GMAIL_APP_PASSWORD`: a Gmail app password for that account.
- `REPORT_TO` (optional): where to send it, if not the same address.

## Running by hand
Actions tab → CSE Daily Stock Focus → Run workflow.
