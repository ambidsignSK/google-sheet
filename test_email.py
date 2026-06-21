#!/usr/bin/env python3
"""Test Gmail SMTP pripojenia - posle testovaci email sam na seba."""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "ambidsign@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

if not GMAIL_APP_PASSWORD:
    print("❌ CHYBA: GMAIL_APP_PASSWORD nie je nastavené v .env súbore")
    print("   Nastav ho na: myaccount.google.com → Zabezpečenie → Heslá aplikácií")
    exit(1)

print(f"📧 Testujem Gmail účet: {GMAIL_ADDRESS}")
print("🔌 Pripájam sa na smtp.gmail.com:465 ...")

try:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "✅ Test – Hotel Backlink Agent funguje"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    text = f"""\
Testovací email z Hotel Backlink Agenta.

Ak vidíš tento email, Gmail SMTP je správne nakonfigurovaný.

Účet: {GMAIL_ADDRESS}
Agent: hotel_backlink_agent.py
"""
    html = f"""\
<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:500px;">
<h2 style="color:#1a56db;">✅ Gmail pripojenie funguje!</h2>
<p>Testovací email z <strong>Hotel Backlink Agenta</strong>.</p>
<p>Účet: <strong>{GMAIL_ADDRESS}</strong></p>
<p style="color:#888;font-size:12px;margin-top:20px;">Môžeš spustiť: <code>python hotel_backlink_agent.py</code></p>
</body></html>"""

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

    print(f"✅ Testovací email odoslaný na {GMAIL_ADDRESS}")
    print("   Skontroluj doručenú poštu (prípadne spam).")

except smtplib.SMTPAuthenticationError:
    print("❌ CHYBA: Nesprávne heslo aplikácie (App Password)")
    print("   1. Over že máš zapnuté dvojstupňové overenie na Google účte")
    print("   2. Vytvor nové heslo: myaccount.google.com → Zabezpečenie → Heslá aplikácií")
    print("   3. Skopíruj 16-znakový kód do .env ako GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")

except smtplib.SMTPException as e:
    print(f"❌ SMTP chyba: {e}")

except Exception as e:
    print(f"❌ Neočakávaná chyba: {e}")
