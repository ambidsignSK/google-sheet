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
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
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
EMAIL_DELAY = int(os.getenv("EMAIL_DELAY", "3"))

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
            time.sleep(0.3)
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
# Zdroj 5: Socialne siete - Facebook, Instagram, TikTok (cez Google)
# ---------------------------------------------------------------------------

def _google_search_urls(query: str, num: int = 10) -> list[str]:
    """Vrati zoznam URL z Google vyhladavania."""
    search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num={num}"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/url?q="):
                actual = href.split("/url?q=")[1].split("&")[0]
                if actual.startswith("http"):
                    urls.append(actual)
        return urls
    except Exception as e:
        log.debug(f"Google search chyba: {e}")
    return []


def _extract_email_from_social_page(url: str) -> str:
    """Pokusi sa najst email na verejnom profile socialnej siete."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        emails = extract_emails_from_text(r.text)
        for e in emails:
            if not any(skip in e for skip in ["facebook", "instagram", "tiktok", "example", "sentry"]):
                return e
    except Exception:
        pass
    return ""


def fetch_from_facebook(country: str = "SK", pages: int = 3) -> list[dict]:
    """Hlada nove firemne Facebook stranky SK/CZ firiem cez Google."""
    companies = []
    keyword = "Slovensko nová firma" if country == "SK" else "Česká republika nová firma"
    query = f'site:facebook.com/pages {keyword}'

    urls = _google_search_urls(query, num=pages * 5)
    for url in urls:
        if "facebook.com" not in url or "/pages/" not in url:
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "lxml")
            name = soup.find("title")
            name = name.get_text(strip=True).replace(" | Facebook", "").replace(" - Facebook", "") if name else ""
            if not name:
                continue
            email = _extract_email_from_social_page(url)
            companies.append({
                "name": name,
                "ico": "",
                "city": "",
                "country": country,
                "detail_url": url,
                "email": email,
                "source": "facebook",
            })
            time.sleep(0.5)
        except Exception as e:
            log.debug(f"Facebook strana {url}: {e}")

    log.info(f"Facebook ({country}): najdených {len(companies)} firiem")
    return companies


def fetch_from_instagram(country: str = "SK", pages: int = 3) -> list[dict]:
    """Hlada firemne Instagram profily SK/CZ firiem cez Google."""
    companies = []
    keyword = "Slovensko firma" if country == "SK" else "Česko firma"
    query = f'site:instagram.com {keyword} kontakt email'

    urls = _google_search_urls(query, num=pages * 5)
    for url in urls:
        if "instagram.com" not in url:
            continue
        parts = [p for p in url.rstrip("/").split("/") if p and "instagram.com" not in p and "?" not in p]
        if not parts:
            continue
        username = parts[-1]
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "lxml")
            email = _extract_email_from_social_page(url)
            # Meno z title
            title = soup.find("title")
            name = title.get_text(strip=True).split("•")[0].strip().split("(")[0].strip() if title else username
            if not name:
                name = username
            companies.append({
                "name": name,
                "ico": "",
                "city": "",
                "country": country,
                "detail_url": url,
                "email": email,
                "source": "instagram",
            })
            time.sleep(0.5)
        except Exception as e:
            log.debug(f"Instagram {url}: {e}")

    log.info(f"Instagram ({country}): najdených {len(companies)} firiem")
    return companies


def fetch_from_tiktok(country: str = "SK", pages: int = 3) -> list[dict]:
    """Hlada firemne TikTok profily SK/CZ firiem cez Google."""
    companies = []
    keyword = "Slovensko firma" if country == "SK" else "Česko firma"
    query = f'site:tiktok.com {keyword} email kontakt'

    urls = _google_search_urls(query, num=pages * 5)
    for url in urls:
        if "tiktok.com" not in url or "/@" not in url:
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "lxml")
            email = _extract_email_from_social_page(url)
            title = soup.find("title")
            name = title.get_text(strip=True).split("|")[0].strip() if title else url
            companies.append({
                "name": name,
                "ico": "",
                "city": "",
                "country": country,
                "detail_url": url,
                "email": email,
                "source": "tiktok",
            })
            time.sleep(0.5)
        except Exception as e:
            log.debug(f"TikTok {url}: {e}")

    log.info(f"TikTok ({country}): najdených {len(companies)} firiem")
    return companies


# ---------------------------------------------------------------------------
# Zdroj 6: Google - dalsi nacitanie web stranok firiem
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

V dnešnej dobe je online viditeľnosť kľúčová pre rýchly rast.
Ponúkame Vám profesionálnu správu PPC reklamy (Google Ads, Meta Ads), špeciálne navrhnutú pre nové firmy.

**Čo získate?**
- Nastavenie a správa Google Ads / Facebook & Instagram reklám
- Cielenie priamo na Vašich ideálnych zákazníkov
- Mesačné reporty a optimalizácia kampaní

**Cenník správy:**
- **Štartér** (rozpočet do 300 €/mes): 200 €/mes
- **Business** (rozpočet do 800 €/mes): 350 €/mes
- **PRO** (nad 800 €/mes): individuálna dohoda

Radi Vám pripravíme bezplatnú analýzu a konkrétny návrh kampane na mieru.

Neváhajte nás kontaktovať – odpovieme do 24 hodín.

S pozdravom

Tomáš Ambroz
@mbi design
+421 907 926 375

Web a Kampaň, ktoré zarábajú.
ambidesign.eu
"""

EMAIL_BODY_CZ = """\
Dobrý den,

V dnešní době je online viditelnost klíčová pro rychlý růst.
Nabízíme Vám profesionální správu PPC reklamy (Google Ads, Meta Ads), speciálně navržené pro nové firmy.

**Co získáte?**
- Nastavení a správa Google Ads / Facebook & Instagram reklamy
- Cílení přímo na Vaše ideální zákazníky
- Měsíční reporty a optimalizace kampaní

**Ceník správy:**
- **Štartér** (rozpočet do 300 €/měs): 200 €/měs
- **Business** (rozpočet do 800 €/měs): 350 €/měs
- **PRO** (nad 800 €/měs): individuální dohoda

Rádi Vám připravíme bezplatnou analýzu a konkrétní návrh kampaně na míru.

Neváhejte nás kontaktovat – odpovíme do 24 hodin.

S pozdravem

Tomáš Ambroz
@mbi design
+421 907 926 375

Web a Kampaň, ktoré zarábajú.
ambidesign.eu
"""


LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.jpg")


def build_html_body(plain_body: str) -> str:
    """Konvertuje plain text na HTML s logom v podpise."""
    # Rozdelime telo a podpis (podpis zacina od "S pozdravom")
    split_marker = None
    if "S pozdravom" in plain_body:
        split_marker = "S pozdravom"
    elif "S pozdravem" in plain_body:
        split_marker = "S pozdravem"

    if split_marker:
        split_at = plain_body.index(split_marker)
        content = plain_body[:split_at].rstrip("\n")
        signature = plain_body[split_at:]
    else:
        content = plain_body
        signature = ""

    def to_html(text: str) -> str:
        import re as _re
        lines = text.split("\n")
        out = ""
        for line in lines:
            if not line.strip():
                # Prazdny riadok = maly odstavec
                out += '<div style="margin:10px 0;"></div>'
                continue
            # Tucny nadpis: **text**
            if line.startswith("**") and line.endswith("**"):
                inner = line[2:-2]
                out += f"<div><strong>{inner}</strong></div>"
            # Odradzky
            elif line.startswith("- "):
                inner = line[2:]
                inner = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', inner)
                out += f"<div>&bull;&nbsp;{inner}</div>"
            # Ostatne riadky
            else:
                line = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                line = _re.sub(r'(?<![">])(ambidesign\.eu)', r'<a href="https://ambidesign.eu" target="_blank">\1</a>', line)
                out += f"<div>{line}</div>"
        return out

    logo_tag = '<a href="https://ambidesign.eu" target="_blank"><img src="cid:logo" alt="Ambi Design" style="max-width:100px;max-height:100px;margin-top:8px;display:block;border:none;"></a>' if os.path.exists(LOGO_PATH) else ""

    html = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5;max-width:600px;">
<div style="margin-bottom:16px;">{to_html(content)}</div>
<div style="font-size:14px;color:#111;line-height:1.6;">{to_html(signature)}</div>
{logo_tag}
</body></html>"""
    return html


SENT_IDS_LOG = "sent_message_ids.json"


def _save_sent_message_id(message_id: str, to_email: str):
    """Ulozi Message-ID odoslaneho emailu pre neskorsi matching odpovedi."""
    data = {}
    if os.path.exists(SENT_IDS_LOG):
        with open(SENT_IDS_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[message_id] = {"to": to_email, "sent_at": datetime.now().isoformat()}
    with open(SENT_IDS_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Odosle email cez Gmail SMTP s logom v podpise."""
    if not GMAIL_APP_PASSWORD:
        log.error("GMAIL_APP_PASSWORD nie je nastavene v .env")
        return False

    try:
        import uuid as _uuid
        message_id = f"<ppc-{_uuid.uuid4().hex}@ambidsign>"

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email
        msg["Bcc"] = GMAIL_ADDRESS
        msg["Message-ID"] = message_id

        alternative = MIMEMultipart("alternative")
        msg.attach(alternative)

        text_part = MIMEText(body, "plain", "utf-8")
        html_part = MIMEText(build_html_body(body), "html", "utf-8")
        alternative.attach(text_part)
        alternative.attach(html_part)

        # Pripoj logo ako inline obrazok
        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, "rb") as f:
                img = MIMEImage(f.read(), _subtype="jpeg")
            img.add_header("Content-ID", "<logo>")
            img.add_header("Content-Disposition", "inline", filename="logo.jpg")
            msg.attach(img)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, [to_email, GMAIL_ADDRESS], msg.as_string())

        # Uloz Message-ID pre neskorsi matching odpovedi
        _save_sent_message_id(message_id, to_email)

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

    # 1. Zbieranie firiem - registre + katalogy (paralelne)
    fetchers = [
        lambda: fetch_new_companies_sk(DAYS_BACK),
        lambda: fetch_new_companies_cz(DAYS_BACK),
        fetch_from_firmy_sk,
        fetch_from_najfirmy_sk,
        fetch_from_zlatestranky_sk,
        fetch_from_firmy_cz,
        fetch_from_zlatestranky_cz,
        lambda: fetch_from_facebook("SK"),
        lambda: fetch_from_facebook("CZ"),
        lambda: fetch_from_instagram("SK"),
        lambda: fetch_from_instagram("CZ"),
        lambda: fetch_from_tiktok("SK"),
        lambda: fetch_from_tiktok("CZ"),
    ]
    companies = []
    with ThreadPoolExecutor(max_workers=13) as ex:
        futures = {ex.submit(fn): fn for fn in fetchers}
        for future in as_completed(futures):
            try:
                companies.extend(future.result())
            except Exception as e:
                log.error(f"Chyba pri ziskavani firiem: {e}")

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

    def enrich_company(company: dict) -> dict:
        if company.get("detail_url") and company["country"] == "SK" and company.get("source") != "firmy.sk":
            detail = get_orsr_detail(company["detail_url"])
            company.update(detail)
        if not company.get("email") and company.get("detail_url") and company.get("source"):
            email = get_email_from_catalog_detail(company["detail_url"], company["country"])
            if email:
                company["email"] = email
        company = enrich_with_google(company)
        return company

    log.info(f"Obohacujem {len(companies)} firiem (paralelne)...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        companies = list(ex.map(enrich_company, companies))

    for i, company in enumerate(companies, 1):
        log.info(f"[{i}/{len(companies)}] {company['name']} ({company['country']})")

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

    # Notifikacie
    if results["total_found"] > 0:
        notify_desktop(
            title=f"PPC Agent – {results['total_found']} nových firiem",
            message=(
                f"Emailov nájdených: {results['emails_found']}\n"
                f"Odoslaných ponúk: {results['emails_sent']}"
            ),
        )
        send_summary_notification(results)

    return results


# ---------------------------------------------------------------------------
# Notifikacie
# ---------------------------------------------------------------------------

def notify_desktop(title: str, message: str):
    """Zobrazi Windows/Mac/Linux desktop notifikaciu."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="PPC Lead Agent",
            timeout=10,
        )
    except Exception as e:
        log.debug(f"Desktop notifikacia zlyhala: {e}")


def send_summary_notification(results: dict):
    """Odosle sumarny email na ambidsign@gmail.com s prehadom behu."""
    if not GMAIL_APP_PASSWORD:
        return

    found = results["total_found"]
    emails_found = results["emails_found"]
    sent_count = results["emails_sent"]

    if found == 0:
        return  # Nic nenajdene, neposielat ziadnu notifikaciu

    # Zoznam firiem s emailom - max 50 riadkov
    rows = ""
    for c in results["companies"]:
        status_icon = {"sent": "✅", "dry_run": "📋", "no_email": "❌", "already_sent": "⏭", "error": "⚠️"}.get(c.get("status", ""), "•")
        email_str = c.get("email", "-")
        source = c.get("source", c.get("country", ""))
        rows += f"{status_icon} {c['name']} | {c.get('city','')} | {email_str} | {source}\n"

    body = f"""PPC Lead Agent - súhrn behu {datetime.now().strftime('%d.%m.%Y %H:%M')}

📊 ŠTATISTIKY:
  Firiem nájdených:   {found}
  Emailov nájdených:  {emails_found}
  Emailov odoslaných: {sent_count}
  Preskočených:       {results['skipped']}

📋 ZOZNAM FIRIEM:
{rows}
---
Legenda: ✅ odoslané | ❌ email nenájdený | ⏭ už odoslané | ⚠️ chyba
"""

    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"[PPC Agent] {found} nových firiem nájdených – {sent_count} emailov odoslaných"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

        log.info(f"Sumarny notifikacny email odoslany na {GMAIL_ADDRESS}")
    except Exception as e:
        log.error(f"Chyba pri odosielani sumarneho emailu: {e}")


def send_to_email(email: str):
    """Odosle cenovu ponuku priamo na zadany email."""
    email = email.strip().lower()
    if not EMAIL_REGEX.match(email):
        log.error(f"Neplatna emailova adresa: {email}")
        return

    if email.endswith(".sk"):
        subject = EMAIL_SUBJECT_SK
        body = EMAIL_BODY_SK
    elif email.endswith(".cz"):
        subject = EMAIL_SUBJECT_CZ
        body = EMAIL_BODY_CZ
    else:
        subject = EMAIL_SUBJECT_SK
        body = EMAIL_BODY_SK

    log.info(f"Odosielam cenovu ponuku na: {email}")
    if GMAIL_APP_PASSWORD:
        success = send_email(email, subject, body)
        if success:
            sent = load_sent()
            sent.add(email)
            save_sent(sent)
    else:
        log.warning(f"[DRY RUN] Email by bol odoslany na: {email}")
        log.warning("Nastav GMAIL_APP_PASSWORD v .env subore")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # python agent.py email@firma.sk
        send_to_email(sys.argv[1])
    else:
        run_agent()
