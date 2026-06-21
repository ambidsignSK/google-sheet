#!/usr/bin/env python3
"""
Hotel Backlink Agent - oslovovanie hotelov v okolí letísk
Hľadá hotely pri letiskách VIE (Viedeň) a BTS (Bratislava) a žiada o spoluprácu / spätný odkaz na taxi-vienna-bratislava.com
"""

import os
import re
import time
import json
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

load_dotenv()

DRY_RUN = False  # nastavuje sa cez --dry-run argument

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("hotel_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "ambidsign@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
EMAIL_DELAY = int(os.getenv("EMAIL_DELAY", "15"))

OUR_WEBSITE = "taxi-vienna-bratislava.com"
OUR_NAME = "Tomáš Ambroz"
OUR_TITLE = "Marketingový manažér"
OUR_COMPANY = "NENBRA s.r.o."
OUR_PHONE = "+421 907 926 375"

SENT_LOG = "hotel_sent_emails.json"
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.jpg")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# ---------------------------------------------------------------------------
# Letiska a oblasti hľadania
# ---------------------------------------------------------------------------

AIRPORT_REGIONS = [
    {
        "airport": "Vienna International Airport (VIE)",
        "country": "AT",
        "lang": "de",
        "queries": [
            "hotel near Vienna airport VIE",
            "hotel Wien Flughafen Schwechat",
            "hotel Schwechat Wien",
            "airport hotel Vienna Schwechat",
            "hotel nahe Flughafen Wien",
        ],
    },
    {
        "airport": "Bratislava Airport (BTS)",
        "country": "SK",
        "lang": "sk",
        "queries": [
            "hotel pri letisku Bratislava BTS",
            "hotel Bratislava letisko",
            "airport hotel Bratislava",
            "hotel Ivanka pri Dunaji letisko",
            "hotel blizko letisku Bratislava",
        ],
    },
    {
        "airport": "Budapest Airport (BUD)",
        "country": "HU",
        "lang": "hu",
        "queries": [
            "hotel Budapest Airport BUD",
            "hotel Ferihegy repülőtér közelében",
            "airport hotel Budapest Liszt Ferenc",
        ],
    },
    {
        "airport": "Brno Airport (BRQ)",
        "country": "CZ",
        "lang": "cs",
        "queries": [
            "hotel letiště Brno Tuřany",
            "hotel Brno letisko airport",
        ],
    },
    {
        "airport": "Prague Airport (PRG)",
        "country": "CZ",
        "lang": "cs",
        "queries": [
            "hotel letiště Praha Václav Havel",
            "hotel Praha Ruzyně letiště",
            "airport hotel Prague PRG",
            "hotel u letiště Praha",
            "hotel Ruzyně Praha airport",
        ],
    },
]

# ---------------------------------------------------------------------------
# Email šablóny v jednotlivých jazykoch
# ---------------------------------------------------------------------------

SUBJECTS = {
    "sk": "Ponuka spolupráce pre Váš hotel – Taxi Viedeň–Bratislava",
    "cs": "Nabídka spolupráce pro Váš hotel – Taxi Vídeň–Bratislava",
    "de": "Kooperationsangebot für Ihr Hotel – Taxi Wien–Bratislava",
    "hu": "Együttműködési ajánlat szállodájának – Taxi Bécs–Pozsony",
    "en": "Partnership Proposal for Your Hotel – Taxi Vienna–Bratislava",
}

BODIES = {
    "sk": """\
Dobrý deň,

obraciam sa na Vás s priateľskou ponukou spolupráce, ktorá by mohla byť prínosom pre nás oboch.

Prevádzkujeme letiskovú taxislužbu **taxi-vienna-bratislava.com** – zabezpečujeme pohodlné a spoľahlivé transfery medzi Viedňou, Bratislavou a okolitými letiskami (VIE, BTS). Naší zákazníci sú práve cestujúci, ktorí vyhľadávajú ubytovanie v oblasti letísk – teda presne Vaši potenciálni hostia.

**Čo navrhujeme?**
Radi by sme nadviazali spoluprácu v niektorej z týchto foriem – podľa toho, čo Vám najviac vyhovuje:

- Výmena partnerských odkazov (my Vás uvedieme v sekcii odporúčaných hotelov, Vy nám odkaz v sekcii „Doprava" alebo „Partneri")
- Umiestnenie nášho reklamného bannera na Vašom webe – dodáme grafiku v požadovanej veľkosti, bez nároku na poplatky
- Kombinácia oboch možností

Táto spolupráca je pre Vás bezplatná a pre Vašich hostí skutočne praktická – môžu si vopred zabezpečiť transfer z letiska priamo k Vám.

Ak Vás niektorá z možností zaujíma, stačí odpovedať na tento email – radi sa dohodneme na detailoch.

Ďakujeme za čas a tešíme sa na prípadnú spoluprácu!

S priateľským pozdravom

{name}
{title} | {company}
Prevádzkovateľ taxi-vienna-bratislava.com
{phone}
www.taxi-vienna-bratislava.com
""",

    "cs": """\
Dobrý den,

obracím se na Vás s přátelskou nabídkou spolupráce, která by mohla být přínosem pro nás oba.

Provozujeme letištní taxislužbu **taxi-vienna-bratislava.com** – zajišťujeme pohodlné a spolehlivé transfery mezi Vídní, Bratislavou a okolními letišti (VIE, BTS). Naší zákazníci jsou právě cestující, kteří hledají ubytování v oblasti letišť – tedy přesně Vaši potenciální hosté.

**Co navrhujeme?**
Rádi bychom navázali spolupráci v některé z těchto forem – podle toho, co Vám nejvíce vyhovuje:

- Výměna partnerských odkazů (my Vás uvedeme v sekci doporučených hotelů, Vy nám odkaz v sekci „Doprava" nebo „Partneři")
- Umístění našeho reklamního banneru na Vašem webu – dodáme grafiku v požadované velikosti, bez nároku na poplatky
- Kombinace obou možností

Tato spolupráce je pro Vás bezplatná a pro Vaše hosty skutečně praktická – mohou si předem zajistit transfer z letiště přímo k Vám.

Pokud Vás některá z možností zaujme, stačí odpovědět na tento email – rádi se domluvíme na detailech.

Děkujeme za čas a těšíme se na případnou spolupráci!

S přátelským pozdravem

{name}
{title} | {company}
Provozovatel taxi-vienna-bratislava.com
{phone}
www.taxi-vienna-bratislava.com
""",

    "de": """\
Guten Tag,

ich melde mich bei Ihnen mit einem freundlichen Kooperationsangebot, das für beide Seiten von Vorteil sein könnte.

Wir betreiben den Flughafentransfer-Service **taxi-vienna-bratislava.com** – wir bieten bequeme und zuverlässige Transfers zwischen Wien, Bratislava und den umliegenden Flughäfen (VIE, BTS). Unsere Kunden sind genau die Reisenden, die in der Nähe der Flughäfen eine Unterkunft suchen – also potenzielle Gäste für Ihr Haus.

**Unser Vorschlag:**
Wir würden uns freuen, eine Zusammenarbeit in einer der folgenden Formen zu starten – ganz wie es für Sie am besten passt:

- Austausch von Partnerlinks (wir nennen Sie in unserer Rubrik „Empfohlene Hotels", Sie verlinken uns unter „Anreise" oder „Partner")
- Platzierung unseres Werbebannners auf Ihrer Website – wir liefern die Grafik in der gewünschten Größe, kostenlos für Sie
- Kombination beider Möglichkeiten

Diese Zusammenarbeit ist für Sie kostenlos und für Ihre Gäste wirklich praktisch – sie können schon im Voraus einen Transfer vom Flughafen direkt zu Ihnen buchen.

Wenn Sie interessiert sind, antworten Sie einfach auf diese E-Mail – wir besprechen gerne die Details.

Vielen Dank für Ihre Zeit und wir freuen uns auf eine mögliche Zusammenarbeit!

Mit freundlichen Grüßen

{name}
{title} | {company}
Betreiber von taxi-vienna-bratislava.com
{phone}
www.taxi-vienna-bratislava.com
""",

    "hu": """\
Tisztelt Hölgyem/Uram,

barátságos együttműködési javaslattal fordulok Önhöz, amely mindkét fél számára előnyös lehet.

Mi a **taxi-vienna-bratislava.com** repülőtéri transzfer szolgáltatást üzemeltetjük – kényelmes és megbízható transzfereket biztosítunk Bécs, Pozsony és a környező repülőterek (VIE, BTS) között. Ügyfeleink pontosan azok az utazók, akik a repülőterek közelében keresnek szállást – tehát az Ön potenciális vendégei.

**Javaslatunk:**
Szívesen indítanánk együttműködést az alábbi formák egyikében – attól függően, ami Önnek a legjobban megfelel:

- Partnerlink-csere (mi feltüntetjük Önt az ajánlott szállodák között, Ön linkel minket a „Megközelítés" vagy „Partnerek" rovatban)
- Reklámbannerünk elhelyezése az Ön weboldalán – a grafikát kívánt méretben szállítjuk, Önnek ingyenesen
- A két lehetőség kombinációja

Ez az együttműködés Önnek ingyenes, és vendégei számára igazán praktikus – így előre megszervezhetik a repülőtéri transzfert közvetlenül az Ön szállodájához.

Ha az ajánlat felkeltette érdeklődését, egyszerűen válaszoljon erre az e-mailre – szívesen egyeztetünk a részletekről.

Köszönjük az idejét, és várjuk esetleges együttműködésünket!

Barátsággal,

{name}
{title} | {company}
A taxi-vienna-bratislava.com üzemeltetője
{phone}
www.taxi-vienna-bratislava.com
""",

    "en": """\
Dear Sir or Madam,

I am reaching out with a friendly cooperation proposal that could be mutually beneficial.

We operate **taxi-vienna-bratislava.com** – a comfortable and reliable airport transfer service between Vienna, Bratislava, and surrounding airports (VIE, BTS). Our customers are exactly the travelers who are looking for accommodation near airports – your potential guests.

**Our proposal:**
We would love to start a cooperation in one of the following forms – whichever works best for you:

- Partner link exchange (we list your hotel on our website under recommended accommodations, you link to us under "Getting Here" or "Partners")
- Placing our advertising banner on your website – we provide the artwork in any size you need, free of charge
- A combination of both options

This cooperation is completely free for you and genuinely practical for your guests – they can arrange their airport transfer directly to your hotel in advance.

If you are interested, simply reply to this email and we can discuss the details.

Thank you for your time, and we look forward to a possible partnership!

Kind regards,

{name}
{title} | {company}
Operator of taxi-vienna-bratislava.com
{phone}
www.taxi-vienna-bratislava.com
""",
}

# ---------------------------------------------------------------------------
# Pomocné funkcie
# ---------------------------------------------------------------------------

def load_sent() -> set:
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent(sent: set):
    with open(SENT_LOG, "w", encoding="utf-8") as f:
        json.dump(list(sent), f, ensure_ascii=False, indent=2)


def extract_emails(text: str) -> list:
    emails = EMAIL_REGEX.findall(text)
    clean = []
    for e in emails:
        e = e.lower().strip(".,;")
        if any(skip in e for skip in [
            "example.com", "test.", "noreply", "no-reply",
            ".png", ".jpg", ".gif", "sentry", "wixpress",
            "schema.org", "w3.org",
        ]):
            continue
        if e not in clean:
            clean.append(e)
    return clean


def get_emails_from_url(url: str, timeout: int = 12) -> list:
    emails = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # mailto links
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                e = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                if e and e not in emails:
                    emails.append(e)

        # text scan
        emails.extend(extract_emails(r.text))

        # kontaktná stránka
        contact_links = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"].lower()
            if any(kw in href or kw in text for kw in [
                "kontakt", "contact", "impress", "impressum",
                "o-nas", "about", "kapcsolat", "kapcsolat",
            ]):
                full = urljoin(url, a["href"])
                if full not in contact_links:
                    contact_links.append(full)

        for cu in contact_links[:3]:
            try:
                cr = requests.get(cu, headers=HEADERS, timeout=10)
                for a in BeautifulSoup(cr.text, "lxml").find_all("a", href=True):
                    if a["href"].startswith("mailto:"):
                        e = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                        if e and e not in emails:
                            emails.append(e)
                emails.extend(extract_emails(cr.text))
            except Exception:
                pass

    except Exception as e:
        log.debug(f"Chyba pri načítaní {url}: {e}")

    seen, result = set(), []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


SKIP_DOMAINS = [
    "google.", "booking.com", "tripadvisor", "expedia",
    "hotels.com", "agoda", "airbnb", "trivago",
    "kayak.", "skyscanner", "yelp.", "facebook.",
    "wikipedia.", "youtube.", "twitter.", "instagram.",
    "maps.google", "translate.google", "hotel.de",
    "hrs.com", "hotelscombined", "lastminute",
]


def google_search_hotels(query: str, num: int = 10) -> list:
    """Hľadá hotely cez DuckDuckGo (bez blokovania)."""
    urls = []

    if DDGS_AVAILABLE:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num * 2):
                    url = r.get("href", "")
                    if url and not any(skip in url for skip in SKIP_DOMAINS):
                        if url not in urls:
                            urls.append(url)
                    if len(urls) >= num:
                        break
            return urls
        except Exception as e:
            log.debug(f"DuckDuckGo search chyba: {e}")
    else:
        log.warning("duckduckgo-search nie je nainštalovaný. Spusti: pip install duckduckgo-search")

    return urls


def detect_hotel_language(url: str, country: str) -> str:
    """Určí jazyk podľa TLD alebo krajiny."""
    domain = urlparse(url).netloc.lower()
    if domain.endswith(".sk"):
        return "sk"
    if domain.endswith(".cz"):
        return "cs"
    if domain.endswith(".at") or domain.endswith(".de") or domain.endswith(".ch"):
        return "de"
    if domain.endswith(".hu"):
        return "hu"
    # Fallback podľa krajiny regiónu
    return {"AT": "de", "SK": "sk", "CZ": "cs", "HU": "hu"}.get(country, "en")


def build_html_body(plain_body: str) -> str:
    import re as _re
    lines = plain_body.split("\n")
    out = ""
    for line in lines:
        if not line.strip():
            out += '<div style="margin:8px 0;"></div>'
            continue
        if line.startswith("**") and line.endswith("**"):
            out += f"<div><strong>{line[2:-2]}</strong></div>"
        elif line.startswith("- "):
            inner = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line[2:])
            out += f"<div>&bull;&nbsp;{inner}</div>"
        else:
            line = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = _re.sub(
                r'(taxi-vienna-bratislava\.com)',
                r'<a href="https://www.taxi-vienna-bratislava.com" target="_blank">\1</a>',
                line,
            )
            out += f"<div>{line}</div>"

    logo_tag = (
        f'<a href="https://www.{OUR_WEBSITE}" target="_blank">'
        f'<img src="cid:logo" alt="Taxi Vienna Bratislava" '
        f'style="max-width:120px;margin-top:12px;display:block;border:none;"></a>'
    ) if os.path.exists(LOGO_PATH) else ""

    return f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.6;max-width:620px;">
<div>{out}</div>
{logo_tag}
</body></html>"""


def send_email(to_email: str, subject: str, body: str) -> bool:
    if not GMAIL_APP_PASSWORD:
        log.error("GMAIL_APP_PASSWORD nie je nastavené v .env")
        return False
    try:
        import uuid as _uuid
        message_id = f"<hotel-backlink-{_uuid.uuid4().hex}@taxivb>"

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email
        msg["Bcc"] = GMAIL_ADDRESS
        msg["Message-ID"] = message_id

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
            server.sendmail(GMAIL_ADDRESS, [to_email, GMAIL_ADDRESS], msg.as_string())

        log.info(f"✅ Email odoslaný na: {to_email}")
        return True
    except Exception as e:
        log.error(f"Chyba pri odosielaní na {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# Hlavná logika agenta
# ---------------------------------------------------------------------------

def run_hotel_agent():
    log.info("=" * 65)
    log.info("Hotel Backlink Agent – START")
    log.info(f"Hľadám hotely pri letiskách pre: {OUR_WEBSITE}")
    log.info("=" * 65)

    sent = load_sent()
    results = {
        "total_urls": 0,
        "emails_found": 0,
        "emails_sent": 0,
        "skipped": 0,
        "hotels": [],
    }

    processed_urls = set()

    for region in AIRPORT_REGIONS:
        log.info(f"\n🛫 Región: {region['airport']} ({region['country']})")

        hotel_urls = []
        for query in region["queries"]:
            log.info(f"   🔍 Hľadám: {query}")
            urls = google_search_hotels(query, num=8)
            for u in urls:
                if u not in hotel_urls:
                    hotel_urls.append(u)
            time.sleep(3)  # zdvorilosť voči Google

        log.info(f"   Nájdených {len(hotel_urls)} unikátnych URL pre región")
        results["total_urls"] += len(hotel_urls)

        for url in hotel_urls:
            if url in processed_urls:
                continue
            processed_urls.add(url)

            domain = urlparse(url).netloc
            log.info(f"   🏨 Spracovávam: {domain}")

            emails = get_emails_from_url(url)
            if not emails:
                log.info(f"      → Email nenájdený")
                results["hotels"].append({"url": url, "region": region["airport"], "status": "no_email"})
                continue

            lang = detect_hotel_language(url, region["country"])
            subject = SUBJECTS.get(lang, SUBJECTS["en"])
            body_template = BODIES.get(lang, BODIES["en"])
            body = body_template.format(name=OUR_NAME, title=OUR_TITLE, company=OUR_COMPANY, phone=OUR_PHONE)

            for email in emails[:1]:  # prvý nájdený email
                results["emails_found"] += 1

                if email in sent:
                    log.info(f"      → {email} už odoslané, preskakujem")
                    results["skipped"] += 1
                    results["hotels"].append({"url": url, "email": email, "region": region["airport"], "status": "already_sent"})
                    continue

                log.info(f"      → Odosielam [{lang.upper()}] na: {email}")

                if DRY_RUN:
                    log.warning(f"      [DRY RUN] Email by bol odoslaný na: {email} [{lang.upper()}]")
                    results["hotels"].append({"url": url, "email": email, "lang": lang, "region": region["airport"], "status": "dry_run"})
                elif GMAIL_APP_PASSWORD:
                    success = send_email(email, subject, body)
                    if success:
                        sent.add(email)
                        save_sent(sent)
                        results["emails_sent"] += 1
                        results["hotels"].append({"url": url, "email": email, "lang": lang, "region": region["airport"], "status": "sent"})
                    else:
                        results["hotels"].append({"url": url, "email": email, "region": region["airport"], "status": "error"})
                else:
                    log.warning(f"      [NO PASSWORD] Email by bol odoslaný na: {email} [{lang.upper()}]")
                    results["hotels"].append({"url": url, "email": email, "lang": lang, "region": region["airport"], "status": "dry_run"})

                time.sleep(EMAIL_DELAY)

    # Uloženie reportu
    report_file = f"hotel_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("\n" + "=" * 65)
    log.info("SÚHRN:")
    log.info(f"  URL hotelov nájdených:   {results['total_urls']}")
    log.info(f"  Emailov nájdených:       {results['emails_found']}")
    log.info(f"  Emailov odoslaných:      {results['emails_sent']}")
    log.info(f"  Preskočených:            {results['skipped']}")
    log.info(f"  Report uložený:          {report_file}")
    log.info("=" * 65)

    _send_summary(results)
    return results


def _send_summary(results: dict):
    if not GMAIL_APP_PASSWORD or results["emails_sent"] == 0:
        return
    rows = ""
    for h in results["hotels"]:
        icon = {"sent": "✅", "dry_run": "📋", "no_email": "❌", "already_sent": "⏭", "error": "⚠️"}.get(h.get("status", ""), "•")
        rows += f"{icon} {h.get('url', '')} | {h.get('email', '-')} | {h.get('lang', '-')} | {h.get('region', '')}\n"

    body = f"""Hotel Backlink Agent – súhrn behu {datetime.now().strftime('%d.%m.%Y %H:%M')}

📊 ŠTATISTIKY:
  URL hotelov:        {results['total_urls']}
  Emailov nájdených:  {results['emails_found']}
  Emailov odoslaných: {results['emails_sent']}
  Preskočených:       {results['skipped']}

📋 HOTELY:
{rows}
---
Legenda: ✅ odoslané | ❌ email nenájdený | ⏭ už odoslané | ⚠️ chyba
"""
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"[Hotel Agent] {results['emails_sent']} emailov odoslaných – backlink kampaň"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        log.info(f"Súhrnný email odoslaný na {GMAIL_ADDRESS}")
    except Exception as e:
        log.error(f"Chyba pri odosielaní súhrnu: {e}")


if __name__ == "__main__":
    import sys
    if "--dry-run" in sys.argv:
        DRY_RUN = True
        log.info("🔍 DRY RUN mód – emaily sa NEODOŠLÚ")
    run_hotel_agent()
