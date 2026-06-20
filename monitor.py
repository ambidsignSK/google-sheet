#!/usr/bin/env python3
"""
Reply Monitor - sleduje odpovede na PPC ponuky, analyzuje ich cez AI
a vytvara draft odpovede v Gmaile. O kazdej odpovedi pride BCC na tvoj email.

Spustenie: python monitor.py
Odporucane: spustat kazdych 15-30 minut cez Task Scheduler (Windows)
"""

import imaplib
import email
import os
import time
import json
import logging
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "ambidsign@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SEEN_LOG = "seen_replies.json"


# ---------------------------------------------------------------------------
# Pomocne funkcie
# ---------------------------------------------------------------------------

def load_seen() -> set:
    if os.path.exists(SEEN_LOG):
        with open(SEEN_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_LOG, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)


def decode_str(s) -> str:
    if s is None:
        return ""
    parts = decode_header(s)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="replace")
        else:
            result += part
    return result


def get_email_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return body.strip()


# ---------------------------------------------------------------------------
# Gmail IMAP - citanie novych odpovedi
# ---------------------------------------------------------------------------

def fetch_replies() -> list[dict]:
    """Prihlasi sa do Gmailu cez IMAP a najde odpovede na nase PPC emaily."""
    replies = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        _, data = mail.search(None, '(SUBJECT "Re:")')
        msg_ids = data[0].split() if data[0] else []

        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = decode_str(msg.get("Subject", ""))

            is_ppc_reply = any(
                kw in subject
                for kw in ["PPC reklama", "PPC reklamy", "cenov", "Cenov", "ponuk", "nabídk"]
            )
            if not is_ppc_reply:
                continue

            msg_uid = msg.get("Message-ID", msg_id.decode())
            sender = decode_str(msg.get("From", ""))
            body = get_email_body(msg)
            date_str = msg.get("Date", "")

            replies.append({
                "uid": msg_uid,
                "sender": sender,
                "subject": subject,
                "body": body,
                "date": date_str,
            })

        mail.logout()
        log.info(f"IMAP: najdených {len(replies)} odpovedi na PPC emaily")
    except Exception as e:
        log.error(f"Chyba pri citani IMAP: {e}")

    return replies


# ---------------------------------------------------------------------------
# AI analyza odpovede a navrh draftu
# ---------------------------------------------------------------------------

def analyze_and_draft(reply: dict) -> str:
    """Pouzije Claude AI na analyzu odpovede a navrhne text draftu."""
    if not ANTHROPIC_API_KEY:
        return _basic_draft()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = f"""Si asistent pre PPC agenturu (ambidsign / @mbi design).
Klient odpovedal na ponuku PPC reklamy. Analyzuj jeho odpoved a navrh krátku, profesionálnu odpoved v rovnakom jazyku ako písal klient.

Odpoved klienta:
---
{reply['body'][:2000]}
---

Pokyny:
- Ak má záujem → poďakuj a navrhni konkrétny termín na call/meeting
- Ak má otázky → odpovedz stručne a ponúkni hovor
- Ak nemá záujem → slušne poďakuj a nechaj dvere otvorené
- Podpis: Tomáš Ambroz / @mbi design / +421 907 926 375 / ambidesign.eu
- Nepoužívaj markdown, iba čistý text
- Max 150 slov"""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        log.error(f"AI analyza zlyhala: {e}")
        return _basic_draft()


def _basic_draft() -> str:
    return """Dobrý deň,

ďakujeme za Vašu odpoveď. Radi Vám poskytneme ďalšie informácie.

Môžem Vám navrhnúť krátky hovor, kde prejdeme Vaše potreby a pripravíme konkrétny návrh kampane?

S pozdravom

Tomáš Ambroz
@mbi design
+421 907 926 375
ambidesign.eu"""


# ---------------------------------------------------------------------------
# Vytvorenie draftu v Gmaile
# ---------------------------------------------------------------------------

def create_gmail_draft(to_email: str, subject: str, body: str) -> bool:
    """Ulozi draft odpovede do Gmailu."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))

        mail.append(
            "[Gmail]/Drafts",
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes(),
        )
        mail.logout()
        log.info(f"Draft vytvoreny pre: {to_email}")
        return True
    except Exception as e:
        log.error(f"Chyba pri vytvarani draftu: {e}")
        return False


# ---------------------------------------------------------------------------
# Notifikacny email pre mna
# ---------------------------------------------------------------------------

def send_notification_email(reply: dict, draft_created: bool):
    """Posle notifikacny email mne o novej odpovedi klienta."""
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"[PPC Agent] Nova odpoved: {reply['subject'][:60]}"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS

        body = f"""Nova odpoved na PPC ponuku!

Od: {reply['sender']}
Predmet: {reply['subject']}
Datum: {reply['date']}

--- SPRAVA KLIENTA ---
{reply['body'][:1000]}

--- {'Draft odpovede bol vytvoreny v Gmaile.' if draft_created else 'Draft sa nepodarilo vytvorit.'} ---
"""
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

        log.info("Notifikacny email odoslany")
    except Exception as e:
        log.error(f"Chyba pri odosielani notifikacneho emailu: {e}")


# ---------------------------------------------------------------------------
# Hlavna logika monitora
# ---------------------------------------------------------------------------

def run_monitor():
    log.info("=" * 60)
    log.info("Reply Monitor - kontrola novych odpovedi")
    log.info("=" * 60)

    if not GMAIL_APP_PASSWORD:
        log.error("GMAIL_APP_PASSWORD nie je nastavene")
        return

    seen = load_seen()
    replies = fetch_replies()

    new_count = 0
    for reply in replies:
        uid = reply["uid"]
        if uid in seen:
            continue

        log.info(f"Nova odpoved od: {reply['sender']}")

        draft_text = analyze_and_draft(reply)

        sender_email = reply["sender"]
        if "<" in sender_email:
            sender_email = sender_email.split("<")[1].rstrip(">")

        draft_created = create_gmail_draft(sender_email, reply["subject"], draft_text)

        send_notification_email(reply, draft_created)

        seen.add(uid)
        save_seen(seen)
        new_count += 1

    log.info(f"Spracovanych novych odpovedi: {new_count}")
    log.info("=" * 60)


if __name__ == "__main__":
    run_monitor()
