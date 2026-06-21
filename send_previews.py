#!/usr/bin/env python3
"""Posle testovaci email v kazdom jazyku na ambidsign@gmail.com."""

import os, smtplib, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv

load_dotenv()

from hotel_backlink_agent import (
    SUBJECTS, BODIES, OUR_NAME, OUR_TITLES, OUR_COMPANY, OUR_PHONE,
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD, LOGO_PATH, build_html_body,
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
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS

        alt = MIMEMultipart("alternative")
        msg.attach(alt)
        alt.attach(MIMEText(body, "plain", "utf-8"))
        alt.attach(MIMEText(build_html_body(body), "html", "utf-8"))

        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, "rb") as f:
                img = MIMEImage(f.read(), _subtype="jpeg")
            img.add_header("Content-ID", "<logo>")
            img.add_header("Content-Disposition", "inline", filename="logo.jpg")
            msg.attach(img)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

        print(f"  ✅ {FLAGS[lang]} {lang.upper()} – odoslaný")
    except Exception as e:
        print(f"  ❌ {lang.upper()} – chyba: {e}")

    time.sleep(2)

print(f"\nSkontroluj doručenú poštu na {GMAIL_ADDRESS}")
