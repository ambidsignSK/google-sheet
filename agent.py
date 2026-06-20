#!/usr/bin/env python3
"""
PPC Lead Agent - hladanie novych firiem na SK/CZ a odosielanie cenovych ponuk
"""

import os
import re
import time
import smtplib
import logging
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "ambidsign@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DAYS_BACK = int(os.getenv("DAYS_BACK", "7"))
EMAIL_DELAY = int(os.getenv("EMAIL_DELAY", "10"))

SENT_LOG = "sent_emails.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


# ---------------------------------------------------------------------------
# Nacitanie / ukladanie uz odoslanych emailov
# ---------------------------------------------------------------------------

def load_sent() -> set:
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent(sent: set):
    with open(SENT_LOG, "w", encoding="utf-8") as f:
        json.dump(list(sent), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Scraping emailov z webu firmy
# ---------------------------------------------------------------------------

def extract_emails_from_text(text: str) -> list[str]:
    emails = EMAIL_REGEX.findall(text)
    clean = []
    for e in emails:
        e = e.lower().strip(".,;")
        if any(skip in e for skip in ["example.com", "test.", "noreply", "no-reply", ".png", ".jpg"]):
            continue
        if e not in clean:
            clean.append(e)
    return clean


def get_emails_from_url(url: str, timeout: int = 10) -> list[str]:
    emails = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Kontaktna stranka
        contact_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).lower()
            if any(kw in href or kw in text for kw in ["kontakt", "contact", "o-nas", "about"]):
                contact_links.append(urljoin(url, a["href"]))

        emails.extend(extract_emails_from_text(r.text))

        # Mailto linky
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                email = a["href"].replace("mailto:", "").split("?")[0].strip()
                if email and email not in emails:
                    emails.append(email.lower())

        # Navstiv kontaktnu stranku
        for contact_url in contact_links[:2]:
            try:
                cr = requests.get(contact_url, headers=HEADERS, timeout=timeout)
                emails.extend(extract_emails_from_text(cr.text))
                soup2 = BeautifulSoup(cr.text, "lxml")
                for a in soup2.find_all("a", href=True):
                    if a["href"].startswith("mailto:"):
                        email = a["href"].replace("mailto:", "").split("?")[0].strip()
                        if email and email.lower() not in emails:
                            emails.append(email.lower())
            except Exception:
                pass

    except Exception as e:
        log.debug(f"Chyba pri nacitani {url}: {e}")

    # Unikatne emaily
    seen = set()
    result = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


def google_find_website(company_name: str, country: str = "sk") -> str | None:
    """Hlada web firmy cez Google (bez API - volny scraping)."""
    query = f'"{company_name}" site:.{country} OR kontakt email'
    search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/url?q="):
                actual = href.split("/url?q=")[1].split("&")[0]
                if actual.startswith("http") and "google" not in actual:
                    return actual
    except Exception as e:
        log.debug(f"Google search chyba: {e}")
    return None


# ---------------------------------------------------------------------------
# Zdroj 1: ORSR.sk - nove firmy (SR)
# ---------------------------------------------------------------------------

def fetch_new_companies_sk(days_back: int = 7) -> list[dict]:
    """Scrapuje nove firmy z ORSR.sk zaregistrovane za poslednych N dni."""
    companies = []
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%d.%m.%Y")
    date_to = datetime.now().strftime("%d.%m.%Y")

    # ORSR API - zoznam novych zapisov
    url = (
        "https://www.orsr.sk/hladaj_subjekt.asp"
        f"?OBMENO=&ICO=&NAZOV=&ulica=&PSC=&OBEC=&KRAJ=0"
        f"&DATZAP_OD={date_from}&DATZAP_DO={date_to}"
        f"&ZAP_DRUH=0&ZAP_TYP=0&SID=0"
        f"&T=0&R=0&S=2&submit=Hladat"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = "windows-1250"
        soup = BeautifulSoup(r.text, "lxml")

        rows = soup.select("table.tab tr")
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) >= 3:
                name_tag = cols[0].find("a")
                name = name_tag.get_text(strip=True) if name_tag else cols[0].get_text(strip=True)
                ico = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                city = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                detail_url = ""
                if name_tag and name_tag.get("href"):
                    detail_url = "https://www.orsr.sk/" + name_tag["href"]

                if name:
                    companies.append({
                        "name": name,
                        "ico": ico,
                        "city": city,
                        "country": "SK",
                        "detail_url": detail_url,
                    })

        log.info(f"ORSR.sk: najdených {len(companies)} novych firiem")
    except Exception as e:
        log.error(f"Chyba pri nacitani ORSR.sk: {e}")

    return companies


def get_orsr_detail(detail_url: str) -> dict:
    """Ziska detailne info o firme z ORSR (web, email)."""
    info = {"web": "", "email": ""}
    if not detail_url:
        return info
    try:
        r = requests.get(detail_url, headers=HEADERS, timeout=10)
        r.encoding = "windows-1250"
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text()
        emails = extract_emails_from_text(text)
        if emails:
            info["email"] = emails[0]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "orsr" not in href:
                info["web"] = href
                break
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Zdroj 2: ARES - nove firmy (CR)
# ---------------------------------------------------------------------------

def fetch_new_companies_cz(days_back: int = 7) -> list[dict]:
    """Pyta ARES API pre nove firmy zaregistrovane za poslednych N dni."""
    companies = []
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    # ARES REST API v1
    url = (
        "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat"
    )
    payload = {
        "datumZapisuOd": date_from,
        "datumZapisuDo": date_to,
        "start": 0,
        "pocet": 50,
        "razeni": ["datumZapisu"],
    }

    try:
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
        data = r.json()
        items = data.get("ekonomickeSubjekty", [])
        for item in items:
            name = item.get("obchodniJmeno", "")
            ico = item.get("ico", "")
            address = item.get("sidlo", {})
            city = address.get("nazevObce", "")
            if name:
                companies.append({
                    "name": name,
                    "ico": ico,
                    "city": city,
                    "country": "CZ",
                    "detail_url": f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}",
                })
        log.info(f"ARES CZ: najdených {len(companies)} novych firiem")
    except Exception as e:
        log.error(f"Chyba pri nacitani ARES: {e}")

    return companies


# ---------------------------------------------------------------------------
# Zdroj 3: Katalogove stranky SK
# ---------------------------------------------------------------------------

def fetch_from_firmy_sk(pages: int = 3) -> list[dict]:
    """Scrapuje nove firmy z firmy.sk (zoradene podla datumu zalozenia)."""
    companies = []
    base = "https://www.firmy.sk/nove-firmy"
    for page in range(1, pages + 1):
        url = f"{base}?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".companyBox, .firmItem, article.company, .searchResult"):
                name_el = item.select_one("h2 a, h3 a, .companyName a, .name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                detail_url = name_el.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.firmy.sk" + detail_url
                city_el = item.select_one(".address, .city, .location")
                city = city_el.get_text(strip=True) if city_el else ""
                email_el = item.select_one("a[href^='mailto:']")
                email = ""
                if email_el:
                    email = email_el["href"].replace("mailto:", "").split("?")[0].strip()
                if name:
                    companies.append({
                        "name": name,
                        "ico": "",
                        "city": city,
                        "country": "SK",
                        "detail_url": detail_url,
                        "email": email,
                        "source": "firmy.sk",
                    })
            time.sleep(1)
        except Exception as e:
            log.debug(f"firmy.sk strana {page}: {e}")
    log.info(f"firmy.sk: najdených {len(companies)} firiem")
    return companies


def fetch_from_najfirmy_sk(pages: int = 3) -> list[dict]:
    """Scrapuje nove firmy z najfirmy.sk."""
    companies = []
    for page in range(1, pages + 1):
        url = f"https://www.najfirmy.sk/nove-firmy/?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".company-item, .firm, .listing-item, article"):
                name_el = item.select_one("h2 a, h3 a, .title a, .name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                detail_url = name_el.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.najfirmy.sk" + detail_url
                city_el = item.select_one(".address, .city, .mesto")
                city = city_el.get_text(strip=True) if city_el else ""
                email = ""
                email_el = item.select_one("a[href^='mailto:']")
                if email_el:
                    email = email_el["href"].replace("mailto:", "").split("?")[0].strip()
                if name:
                    companies.append({
                        "name": name,
                        "ico": "",
                        "city": city,
                        "country": "SK",
                        "detail_url": detail_url,
                        "email": email,
                        "source": "najfirmy.sk",
                    })
            time.sleep(1)
        except Exception as e:
            log.debug(f"najfirmy.sk strana {page}: {e}")
    log.info(f"najfirmy.sk: najdených {len(companies)} firiem")
    return companies


def fetch_from_zlatestranky_sk(pages: int = 3) -> list[dict]:
    """Scrapuje nove firmy zo zlatestranky.sk."""
    companies = []
    for page in range(1, pages + 1):
        url = f"https://www.zlatestranky.sk/nove-firmy/?stranka={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".company, .result-item, .zs-company, article"):
                name_el = item.select_one("h2 a, h3 a, .company-name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                detail_url = name_el.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.zlatestranky.sk" + detail_url
                city_el = item.select_one(".address, .city, .obec")
                city = city_el.get_text(strip=True) if city_el else ""
                email = ""
                email_el = item.select_one("a[href^='mailto:']")
                if email_el:
                    email = email_el["href"].replace("mailto:", "").split("?")[0].strip()
                if name:
                    companies.append({
                        "name": name,
                        "ico": "",
                        "city": city,
                        "country": "SK",
                        "detail_url": detail_url,
                        "email": email,
                        "source": "zlatestranky.sk",
                    })
            time.sleep(1)
        except Exception as e:
            log.debug(f"zlatestranky.sk strana {page}: {e}")
    log.info(f"zlatestranky.sk: najdených {len(companies)} firiem")
    return companies


# ---------------------------------------------------------------------------
# Zdroj 4: Katalogove stranky CZ
# ---------------------------------------------------------------------------

def fetch_from_firmy_cz(pages: int = 3) -> list[dict]:
    """Scrapuje nove firmy z firmy.cz."""
    companies = []
    for page in range(1, pages + 1):
        url = f"https://www.firmy.cz/nove-firmy?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".companyListItem, .firm-item, article.company, .result"):
                name_el = item.select_one("h2 a, h3 a, .companyTitle a, .name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                detail_url = name_el.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.firmy.cz" + detail_url
                city_el = item.select_one(".address, .city, .locality")
                city = city_el.get_text(strip=True) if city_el else ""
                email = ""
                email_el = item.select_one("a[href^='mailto:']")
                if email_el:
                    email = email_el["href"].replace("mailto:", "").split("?")[0].strip()
                if name:
                    companies.append({
                        "name": name,
                        "ico": "",
                        "city": city,
                        "country": "CZ",
                        "detail_url": detail_url,
                        "email": email,
                        "source": "firmy.cz",
                    })
            time.sleep(1)
        except Exception as e:
            log.debug(f"firmy.cz strana {page}: {e}")
    log.info(f"firmy.cz: najdených {len(companies)} firiem")
    return companies


def fetch_from_zlatestranky_cz(pages: int = 3) -> list[dict]:
    """Scrapuje nove firmy zo zlatestranky.cz."""
    companies = []
    for page in range(1, pages + 1):
        url = f"https://www.zlatestranky.cz/nove-firmy/?stranka={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".company, .result-item, article"):
                name_el = item.select_one("h2 a, h3 a, .company-name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                detail_url = name_el.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.zlatestranky.cz" + detail_url
                city_el = item.select_one(".address, .city")
                city = city_el.get_text(strip=True) if city_el else ""
                email = ""
                email_el = item.select_one("a[href^='mailto:']")
                if email_el:
                    email = email_el["href"].replace("mailto:", "").split("?")[0].strip()
                if name:
                    companies.append({
                        "name": name,
                        "ico": "",
                        "city": city,
                        "country": "CZ",
                        "detail_url": detail_url,
                        "email": email,
                        "source": "zlatestranky.cz",
                    })
            time.sleep(1)
        except Exception as e:
            log.debug(f"zlatestranky.cz strana {page}: {e}")
    log.info(f"zlatestranky.cz: najdených {len(companies)} firiem")
    return companies


def get_email_from_catalog_detail(detail_url: str, country: str) -> str:
    """Nacita detail firmy z katalogov a skusi najst email."""
    if not detail_url:
        return ""
    try:
        r = requests.get(detail_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        # Mailto linky
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                return a["href"].replace("mailto:", "").split("?")[0].strip().lower()
        # Text email
        emails = extract_emails_from_text(soup.get_text())
        if emails:
            return emails[0]
        # Web link z detailu -> scraping kontaktnej stranky
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and not any(
                d in href for d in ["firmy.sk", "najfirmy", "zlatestranky", "firmy.cz", "google", "facebook"]
            ):
                emails = get_emails_from_url(href)
                if emails:
                    return emails[0]
                break
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Zdroj 5: Google - dalsi nacitanie web stranok firiem
# ---------------------------------------------------------------------------

def enrich_with_google(company: dict) -> dict:
    """Pokusi sa najst web a email firmy cez Google."""
    if company.get("email"):
        return company

    country_tld = "sk" if company["country"] == "SK" else "cz"
    web = google_find_website(company["name"], country_tld)
    if web:
        company["web"] = web
        emails = get_emails_from_url(web)
        if emails:
            company["email"] = emails[0]
        time.sleep(2)  # slusnost voci Google

    return company


# ---------------------------------------------------------------------------
# Email - cenova ponuka PPC
# ---------------------------------------------------------------------------

EMAIL_SUBJECT_SK = "Cenová ponuka: PPC reklama pre Vašu novú firmu"
EMAIL_SUBJECT_CZ = "Cenová nabídka: PPC reklama pro Vaši novou firmu"

EMAIL_BODY_SK = """\
Dobrý deň,

gratulujeme k založeniu Vašej novej spoločnosti!

V dnešnej dobe je online viditeľnosť kľúčová pre rýchly rast. Ponúkame Vám profesionálnu správu PPC reklamy (Google Ads, Meta Ads), špeciálne navrhnutú pre nové firmy.

**Čo získate?**
- Nastavenie a správa Google Ads / Facebook & Instagram reklám
- Cielenie priamo na Vašich ideálnych zákazníkov
- Mesačné reporty a optimalizácia kampaní
- Prvý mesiac správy ZADARMO (pri podpise zmluvy na 3 mesiace)

**Cenník správy:**
- Starter (rozpočet do 300 €/mes): 159 €/mes
- Business (rozpočet do 800 €/mes): 259 €/mes
- Pro (nad 800 €/mes): individuálna dohoda

Radi Vám pripravíme bezplatnú analýzu a konkrétny návrh kampane na mieru.

Neváhajte nás kontaktovať – odpovieme do 24 hodín.

S pozdravom,
Tím ambidsign
ambidsign@gmail.com
"""

EMAIL_BODY_CZ = """\
Dobrý den,

gratulujeme k založení Vaší nové společnosti!

V dnešní době je online viditelnost klíčová pro rychlý růst. Nabízíme Vám profesionální správu PPC reklamy (Google Ads, Meta Ads), speciálně navržené pro nové firmy.

**Co získáte?**
- Nastavení a správa Google Ads / Facebook & Instagram reklamy
- Cílení přímo na Vaše ideální zákazníky
- Měsíční reporty a optimalizace kampaní
- První měsíc správy ZDARMA (při podpisu smlouvy na 3 měsíce)

**Ceník správy:**
- Starter (rozpočet do 300 €/měs): 159 €/měs
- Business (rozpočet do 800 €/měs): 259 €/měs
- Pro (nad 800 €/měs): individuální dohoda

Rádi Vám připravíme bezplatnou analýzu a konkrétní návrh kampaně na míru.

Neváhejte nás kontaktovat – odpovíme do 24 hodin.

S pozdravem,
Tým ambidsign
ambidsign@gmail.com
"""


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Odosle email cez Gmail SMTP."""
    if not GMAIL_APP_PASSWORD:
        log.error("GMAIL_APP_PASSWORD nie je nastavene v .env")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email

        # Plain text aj HTML verzia
        text_part = MIMEText(body, "plain", "utf-8")
        html_body = body.replace("\n", "<br>").replace("**", "<b>").replace("**", "</b>")
        html_part = MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8")
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())

        log.info(f"Email odoslany na: {to_email}")
        return True

    except Exception as e:
        log.error(f"Chyba pri odosielani emailu na {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# Hlavna logika agenta
# ---------------------------------------------------------------------------

def run_agent():
    log.info("=" * 60)
    log.info("PPC Lead Agent - start")
    log.info(f"Hladam firmy za poslednych {DAYS_BACK} dni")
    log.info("=" * 60)

    sent = load_sent()

    # 1. Zbieranie firiem - registre + katalogy
    companies = []
    companies.extend(fetch_new_companies_sk(DAYS_BACK))
    companies.extend(fetch_new_companies_cz(DAYS_BACK))
    companies.extend(fetch_from_firmy_sk())
    companies.extend(fetch_from_najfirmy_sk())
    companies.extend(fetch_from_zlatestranky_sk())
    companies.extend(fetch_from_firmy_cz())
    companies.extend(fetch_from_zlatestranky_cz())

    # Deduplikacia podla nazvu firmy
    seen_names = set()
    unique = []
    for c in companies:
        key = c["name"].lower().strip()
        if key not in seen_names:
            seen_names.add(key)
            unique.append(c)
    companies = unique
    log.info(f"Po deduplikacii: {len(companies)} unikatnych firiem")

    log.info(f"Celkom najdených firiem: {len(companies)}")

    results = {
        "total_found": len(companies),
        "emails_found": 0,
        "emails_sent": 0,
        "skipped": 0,
        "companies": [],
    }

    for i, company in enumerate(companies, 1):
        log.info(f"[{i}/{len(companies)}] Spracovavam: {company['name']} ({company['country']})")

        # 2. Ziskat email z ORSR detail
        if company.get("detail_url") and company["country"] == "SK" and company.get("source") != "firmy.sk":
            detail = get_orsr_detail(company["detail_url"])
            company.update(detail)

        # 2b. Email z katalogoveho detailu (firmy.sk, najfirmy.sk atd.)
        if not company.get("email") and company.get("detail_url") and company.get("source"):
            email = get_email_from_catalog_detail(company["detail_url"], company["country"])
            if email:
                company["email"] = email

        # 3. Obohatit cez Google ak este nemas email
        company = enrich_with_google(company)

        email = company.get("email", "")

        if not email:
            log.info(f"  -> Email nenajdeny, preskakujem")
            results["companies"].append({**company, "status": "no_email"})
            continue

        results["emails_found"] += 1

        if email in sent:
            log.info(f"  -> Email {email} uz bol odoslany, preskakujem")
            results["skipped"] += 1
            results["companies"].append({**company, "status": "already_sent"})
            continue

        # 4. Odoslat cenovu ponuku - jazyk podla domeny emailu
        if email.endswith(".sk"):
            subject = EMAIL_SUBJECT_SK
            body = EMAIL_BODY_SK
        elif email.endswith(".cz"):
            subject = EMAIL_SUBJECT_CZ
            body = EMAIL_BODY_CZ
        else:
            # Pre ostatne domeny (.com, .eu atd.) podla krajiny firmy
            if company["country"] == "SK":
                subject = EMAIL_SUBJECT_SK
                body = EMAIL_BODY_SK
            else:
                subject = EMAIL_SUBJECT_CZ
                body = EMAIL_BODY_CZ

        if GMAIL_APP_PASSWORD:
            success = send_email(email, subject, body)
            if success:
                sent.add(email)
                save_sent(sent)
                results["emails_sent"] += 1
                results["companies"].append({**company, "status": "sent"})
            else:
                results["companies"].append({**company, "status": "error"})
        else:
            log.warning(f"  [DRY RUN] Email by bol odoslany na: {email}")
            results["companies"].append({**company, "status": "dry_run"})

        time.sleep(EMAIL_DELAY)

    # 5. Sumarny report
    report_file = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("=" * 60)
    log.info("SUMAR:")
    log.info(f"  Firiem najdených:    {results['total_found']}")
    log.info(f"  Emailov najdených:   {results['emails_found']}")
    log.info(f"  Emailov odoslaných:  {results['emails_sent']}")
    log.info(f"  Preskočených:        {results['skipped']}")
    log.info(f"  Report uložený do:   {report_file}")
    log.info("=" * 60)

    return results


if __name__ == "__main__":
    run_agent()
