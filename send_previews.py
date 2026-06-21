#!/usr/bin/env python3
"""Posle testovaci email v kazdom jazyku na ambidsign@gmail.com."""

import os, smtplib, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

from hotel_backlink_agent import (
    SUBJECTS, BODIES, OUR_NAME, OUR_TITLES, OUR_COMPANY, OUR_PHONE,
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD, build_html_body,
)

if not GMAIL_APP_PASSWORD:
    print("❌ GMAIL_APP_PASSWORD nie je nastavené v .env")
    exit(1)

LANGS = ["sk", "cs", "de", "hu", "en"]
FLAGS = {"sk": "🇸🇰", "cs": "🇨🇿", "de": "🇦🇹", "hu": "🇭🇺", "en": "🌐"}

print(f"Odosielam preview emaily na {GMAIL_ADDRESS}\n")

for lang in LANGS:
    title = OUR_TITLES.get(lang, OUR_TITLES["en"])
    body = BODIES[lang].format(name=OUR_NAME, title=title, company=OUR_COMPANY, phone=OUR_PHONE)
    subject = f"{FLAGS[lang]} [PREVIEW {lang.upper()}] {SUBJECTS[lang]}"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS

        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(build_html_body(body), "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

        print(f"  ✅ {FLAGS[lang]} {lang.upper()} – odoslaný")
    except Exception as e:
        print(f"  ❌ {lang.upper()} – chyba: {e}")

    time.sleep(2)

print(f"\nSkontroluj doručenú poštu na {GMAIL_ADDRESS}")
