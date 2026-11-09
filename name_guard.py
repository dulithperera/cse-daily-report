"""Blocks any report, email or file that mentions names the owner must never use.
Names are stored encoded so they never appear in this repository as plain text."""
import base64, re, subprocess, sys

BLOCKED = [base64.b64decode(b).decode() for b in ["Y2FwaXRhbHRydXN0"]]


def find(text):
    squeezed = re.sub(r"[^a-z]", "", text.lower())
    return [n for n in BLOCKED if n in squeezed]


def check_text(text, where):
    if find(text):
        sys.exit(f"Blocked: {where} contains a name that must not be used. Nothing was sent.")


if __name__ == "__main__":
    # usage: python name_guard.py file [file ...]  (PDFs are checked via their text)
    for path in sys.argv[1:]:
        if path.lower().endswith(".pdf"):
            text = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True).stdout
        else:
            text = open(path, encoding="utf-8", errors="ignore").read()
        check_text(text, path)
    print("Name check passed.")
