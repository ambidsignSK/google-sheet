#!/usr/bin/env python3
"""
Reply Monitor - sleduje odpovede na PPC ponuky, analyzuje ich cez AI,
vytvara draft odpovede v Gmaile a posiela WhatsApp notifikaciu.

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
import requests
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic
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
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "")    # tvoje cislo s pred. kodom napr. +421907926375
WHATSAPP_GROUP = os.getenv("WHATSAPP_GROUP", "")    # nazov WhatsApp skupiny (volitelne)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SEEN_LOG = "seen_replies.json"

# Predmet emailov ktore sme poslali - podla toho filtrujeme odpovede
SENT_SUBJECTS = [
    "Cenová ponuka: PPC reklama pre Vašu novú firmu",
    "Cenová nabídka: PPC reklama pro Vaši novou firmu",
]


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
    """Prihlasi sa do Gmailu cez IMAP a najde odpovede na nase emaily."""
    replies = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Hladame emaily s Re: v predmete ktore su odpovede na nase PPC emaily
        search_queries = []
        for subj in SENT_SUBJECTS:
            short = subj[:30]
            _, data = mail.search(None, f'(SUBJECT "Re:" SUBJECT "{short[:20]}")')
            if data[0]:
                search_queries.extend(data[0].split())

        # Aj generalne - emaily od klientov ktore odpovedaju na naše
        _, data = mail.search(None, '(SUBJECT "Re: Cenov")')
        if data[0]:
            search_queries.extend(data[0].split())

        # Unikatne ID
        msg_ids = list(set(search_queries))

        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            msg_uid = msg.get("Message-ID", msg_id.decode())
            sender = decode_str(msg.get("From", ""))
            subject = decode_str(msg.get("Subject", ""))
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
        log.info(f"IMAP: najdených {len(replies)} odpovedi")
    except Exception as e:
        log.error(f"Chyba pri citani IMAP: {e}")

    return replies


# ---------------------------------------------------------------------------
# AI analyza odpovede a navrh draftu
# ---------------------------------------------------------------------------

def analyze_and_draft(reply: dict) -> str:
    """Pouzije Claude AI na analyzu odpovede a navrhne text draftu."""
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY nie je nastavene - pouzivam zakladny draft")
        return _basic_draft(reply)

    try:
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
        return _basic_draft(reply)


def _basic_draft(reply: dict) -> str:
    """Zakladny draft bez AI."""
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
    """Ulozi draft odpovede priamo do Gmailu cez SMTP (ako draft)."""
    try:
        import base64
        # Gmail draft cez IMAP APPEND
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Uloz do Drafts priecinku
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
# WhatsApp notifikacia cez WhatsApp Web (pywhatkit)
# ---------------------------------------------------------------------------

def send_whatsapp(message: str) -> bool:
    """Posle WhatsApp spravu cez WhatsApp Web v prehliadaci."""
    if not WHATSAPP_PHONE and not WHATSAPP_GROUP:
        log.warning("WHATSAPP_PHONE alebo WHATSAPP_GROUP nie su nastavene v .env")
        return False

    try:
        import pywhatkit as pwk

        if WHATSAPP_GROUP:
            # Posli do skupiny podla nazvu
            pwk.sendwhatmsg_to_group_instantly(
                group_id=WHATSAPP_GROUP,
                message=message,
                wait_time=10,
                tab_close=True,
                close_time=3,
            )
        else:
            # Posli priamo na cislo
            pwk.sendwhatmsg_instantly(
                phone_no=WHATSAPP_PHONE,
                message=message,
                wait_time=10,
                tab_close=True,
                close_time=3,
            )

        log.info("WhatsApp notifikacia odoslana cez WhatsApp Web")
        return True

    except Exception as e:
        log.error(f"WhatsApp chyba: {e}")
        return False


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
            log.info(f"Uz spracovane: {reply['subject'][:50]}")
            continue

        log.info(f"Nova odpoved od: {reply['sender']}")
        log.info(f"Predmet: {reply['subject']}")

        # 1. AI analyza a navrh draftu
        draft_text = analyze_and_draft(reply)

        # 2. Vytvor draft v Gmaile
        # Ziskaj email adresu zo sendera
        sender_email = reply["sender"]
        if "<" in sender_email:
            sender_email = sender_email.split("<")[1].rstrip(">")

        draft_created = create_gmail_draft(
            to_email=sender_email,
            subject=reply["subject"],
            body=draft_text,
        )

        # 3. WhatsApp notifikacia
        wa_msg = (
            f"📩 *Nova odpoved na PPC ponuku!*\n\n"
            f"Od: {reply['sender']}\n"
            f"Predmet: {reply['subject']}\n\n"
            f"_{reply['body'][:200]}..._\n\n"
            f"{'✅ Draft vytvoreny v Gmaile' if draft_created else '⚠️ Draft sa nepodarilo vytvorit'}"
        )
        send_whatsapp(wa_msg)

        seen.add(uid)
        save_seen(seen)
        new_count += 1

    log.info(f"Spracovanych novych odpovedi: {new_count}")
    log.info("=" * 60)


if __name__ == "__main__":
    run_monitor()
