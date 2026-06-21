#!/usr/bin/env python3
"""Posle ukazku emailu v zvolenom jazyku na tvoju adresu."""

import os, sys, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

from hotel_backlink_agent import (
    SUBJECTS, BODIES, OUR_NAME, OUR_TITLES, OUR_COMPANY, OUR_PHONE,
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD, build_html_body,
)

lang = sys.argv[1] if len(sys.argv) > 1 else "sk"
lang = {"cz": "cs"}.get(lang, lang)  # alias
if lang not in SUBJECTS:
    print(f"Neznamy jazyk: {lang}. Moznosti: {', '.join(SUBJECTS.keys())}")
    sys.exit(1)

subject = f"[PREVIEW {lang.upper()}] {SUBJECTS[lang]}"
title = OUR_TITLES.get(lang, OUR_TITLES["en"])
body = BODIES[lang].format(name=OUR_NAME, title=title, company=OUR_COMPANY, phone=OUR_PHONE)

print("=" * 60)
print(f"PREDMET: {SUBJECTS[lang]}")
print("=" * 60)
print(body)
print("=" * 60)

if GMAIL_APP_PASSWORD:
    answer = input(f"\nPoslat preview na {GMAIL_ADDRESS}? [a/n]: ").strip().lower()
    if answer in ("a", "y", ""):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(build_html_body(body), "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            s.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        print(f"✅ Preview odoslany na {GMAIL_ADDRESS}")
