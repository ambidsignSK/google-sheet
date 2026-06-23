#!/usr/bin/env python3
"""
Email Finder - hladanie emailových kontaktov firiem na SK/CZ weboch.
Pouzitie: python email_finder.py "Názov firmy" [sk|cz]
"""

import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en;q=0.7",
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

SKIP_EMAILS = {
    "example.com", "test.", "noreply", "no-reply", ".png", ".jpg",
    "sentry", "w3.org", "schema.org", "googleapis", "cloudflare",
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com",
    "google.com", "apple.com", "microsoft.com",
}


def clean_emails(raw: list[str]) -> list[str]:
    result = []
    seen = set()
    for e in raw:
        e = e.lower().strip(".,;")
        if e in seen:
            continue
        if any(s in e for s in SKIP_EMAILS):
            continue
        seen.add(e)
        result.append(e)
    return result


def extract_emails(text: str) -> list[str]:
    return clean_emails(EMAIL_REGEX.findall(text))


def scrape_emails_from_url(url: str, follow_contact: bool = True, timeout: int = 10) -> list[str]:
    """Stiahne stranku a hlada emaily + navstivi /kontakt stranku."""
    emails = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        soup = BeautifulSoup(r.text, "lxml")

        # mailto linky
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                e = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                if e:
                    emails.append(e)

        emails.extend(extract_emails(r.text))

        if follow_contact:
            contact_urls = []
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                text = a.get_text(strip=True).lower()
                if any(kw in href or kw in text for kw in ["kontakt", "contact", "o-nas", "o-nas", "about", "o-firme"]):
                    full = urljoin(url, a["href"])
                    if full not in contact_urls:
                        contact_urls.append(full)

            for curl in contact_urls[:2]:
                try:
                    cr = requests.get(curl, headers=HEADERS, timeout=timeout)
                    soup2 = BeautifulSoup(cr.text, "lxml")
                    for a in soup2.find_all("a", href=True):
                        if a["href"].startswith("mailto:"):
                            e = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                            if e:
                                emails.append(e)
                    emails.extend(extract_emails(cr.text))
                except Exception:
                    pass

    except Exception as e:
        log.debug(f"scrape_emails_from_url {url}: {e}")

    return clean_emails(emails)


# ---------------------------------------------------------------------------
# ORSR.sk
# ---------------------------------------------------------------------------

def find_on_orsr(company_name: str) -> list[str]:
    url = f"https://www.orsr.sk/hladaj_subjekt.asp?OBMENO={quote(company_name)}&SID=0&T=0&R=0&S=2&submit=Hladat"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.encoding = "windows-1250"
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("table.tab tr td a"):
            href = a.get("href", "")
            if "subjekt" in href:
                detail = "https://www.orsr.sk/" + href
                dr = requests.get(detail, headers=HEADERS, timeout=10)
                dr.encoding = "windows-1250"
                emails = extract_emails(dr.text)
                if emails:
                    log.info(f"ORSR: {emails[0]}")
                    return emails
    except Exception as e:
        log.debug(f"ORSR chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Živnostenský register
# ---------------------------------------------------------------------------

def find_on_zivnostensky(company_name: str) -> list[str]:
    url = f"https://www.zivnostensky-register.sk/?meno={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        emails = extract_emails(r.text)
        if emails:
            log.info(f"Živnostenský register: {emails[0]}")
            return emails
        for a in soup.select("a.detail, .result a, table a"):
            href = a.get("href", "")
            if href and "zivnostensky" in href:
                detail_emails = scrape_emails_from_url(urljoin(url, href), follow_contact=False)
                if detail_emails:
                    return detail_emails
    except Exception as e:
        log.debug(f"Živnostenský register chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# ARES CZ
# ---------------------------------------------------------------------------

def find_on_ares(company_name: str) -> list[str]:
    url = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat"
    try:
        r = requests.post(url, json={"obchodniJmeno": company_name, "pocet": 5},
                          headers={**HEADERS, "Content-Type": "application/json"}, timeout=12)
        items = r.json().get("ekonomickeSubjekty", [])
        for item in items:
            ico = item.get("ico", "")
            if not ico:
                continue
            detail = requests.get(
                f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}",
                headers=HEADERS, timeout=10
            )
            data = detail.json()
            email = data.get("email", "") or data.get("emailKontakt", "")
            if email:
                log.info(f"ARES: {email}")
                return [email.lower()]
    except Exception as e:
        log.debug(f"ARES chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Justice.cz
# ---------------------------------------------------------------------------

def find_on_justice(company_name: str) -> list[str]:
    url = f"https://or.justice.cz/ias/ui/rejstrik-firma.vysledky?subjektId=&typ=PLATNY&nazev={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a[href*='subjektId']"):
            href = urljoin(url, a["href"])
            emails = scrape_emails_from_url(href, follow_contact=False)
            if emails:
                log.info(f"Justice.cz: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Justice.cz chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Finstat.sk
# ---------------------------------------------------------------------------

def find_on_finstat(company_name: str) -> list[str]:
    url = f"https://finstat.sk/databaza-firiem-organizacii?Search={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".company-name a, h3 a, .title a"):
            href = a.get("href", "")
            if not href:
                continue
            detail = urljoin("https://finstat.sk", href)
            emails = scrape_emails_from_url(detail, follow_contact=False)
            if emails:
                log.info(f"Finstat: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Finstat chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Firmy.sk
# ---------------------------------------------------------------------------

def find_on_firmy_sk(company_name: str) -> list[str]:
    url = f"https://www.firmy.sk/?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".companyBox a, .companyName a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href or "firmy.sk" not in href:
                continue
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Firmy.sk: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Firmy.sk chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Firmy.cz
# ---------------------------------------------------------------------------

def find_on_firmy_cz(company_name: str) -> list[str]:
    url = f"https://www.firmy.cz/?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".companyListItem a, .companyTitle a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.firmy.cz", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Firmy.cz: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Firmy.cz chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Zlaté stránky SK
# ---------------------------------------------------------------------------

def find_on_zlatestranky_sk(company_name: str) -> list[str]:
    url = f"https://www.zlatestranky.sk/hladanie/?what={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".company-name a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.zlatestranky.sk", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Zlaté stránky SK: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Zlaté stránky SK chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Zlaté stránky CZ
# ---------------------------------------------------------------------------

def find_on_zlatestranky_cz(company_name: str) -> list[str]:
    url = f"https://www.zlatestranky.cz/hledani/?what={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".company-name a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.zlatestranky.cz", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Zlaté stránky CZ: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Zlaté stránky CZ chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Najfirmy.sk
# ---------------------------------------------------------------------------

def find_on_najfirmy(company_name: str) -> list[str]:
    url = f"https://www.najfirmy.sk/?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".company-item a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.najfirmy.sk", href)
            emails = scrape_emails_from_url(href, follow_contact=False)
            if emails:
                log.info(f"Najfirmy.sk: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Najfirmy.sk chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Zoznam.sk
# ---------------------------------------------------------------------------

def find_on_zoznam(company_name: str) -> list[str]:
    url = f"https://www.zoznam.sk/sk/vyhladavanie/?co={quote(company_name)}&st=SR"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        emails = extract_emails(r.text)
        if emails:
            log.info(f"Zoznam.sk: {emails[0]}")
            return emails
        for a in soup.select(".result a, .listing a, h2 a"):
            href = a.get("href", "")
            if href and href.startswith("http") and "zoznam.sk" not in href:
                emails = scrape_emails_from_url(href, follow_contact=False)
                if emails:
                    return emails
    except Exception as e:
        log.debug(f"Zoznam.sk chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Mojedelo.com
# ---------------------------------------------------------------------------

def find_on_mojedelo(company_name: str) -> list[str]:
    url = f"https://www.mojedelo.com/firmy?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".company a, h2 a, h3 a, .firm-name a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.mojedelo.com", href)
            emails = scrape_emails_from_url(href, follow_contact=False)
            if emails:
                log.info(f"Mojedelo: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Mojedelo chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Europages
# ---------------------------------------------------------------------------

def find_on_europages(company_name: str, country: str = "SK") -> list[str]:
    cc = "sk" if country == "SK" else "cz"
    url = f"https://www.europages.sk/companies/{quote(company_name)}.html?countryCode={cc.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        emails = extract_emails(r.text)
        if emails:
            log.info(f"Europages: {emails[0]}")
            return emails
    except Exception as e:
        log.debug(f"Europages chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Heureka.sk / Heureka.cz
# ---------------------------------------------------------------------------

def find_on_heureka(company_name: str, country: str = "SK") -> list[str]:
    domain = "heureka.sk" if country == "SK" else "heureka.cz"
    url = f"https://{domain}/obchody/?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".shop-name a, h2 a, h3 a, .title a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin(f"https://{domain}", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Heureka ({country}): {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Heureka chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Pricemania.sk
# ---------------------------------------------------------------------------

def find_on_pricemania(company_name: str) -> list[str]:
    url = f"https://www.pricemania.sk/obchody/?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".shop a, h2 a, h3 a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.pricemania.sk", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Pricemania: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Pricemania chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Favi.sk
# ---------------------------------------------------------------------------

def find_on_favi(company_name: str) -> list[str]:
    url = f"https://www.favi.sk/search?q={quote(company_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select(".shop a, h2 a, h3 a, .brand a"):
            href = a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.favi.sk", href)
            emails = scrape_emails_from_url(href, follow_contact=True)
            if emails:
                log.info(f"Favi.sk: {emails[0]}")
                return emails
    except Exception as e:
        log.debug(f"Favi.sk chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Facebook (verejne stranky)
# ---------------------------------------------------------------------------

def find_on_facebook(company_name: str) -> list[str]:
    search_url = f"https://www.google.com/search?q=site:facebook.com+{quote(company_name)}+email"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/url?q=" in href:
                actual = href.split("/url?q=")[1].split("&")[0]
                if "facebook.com" in actual and "/pages/" in actual.lower():
                    emails = scrape_emails_from_url(actual, follow_contact=False)
                    if emails:
                        log.info(f"Facebook: {emails[0]}")
                        return emails
    except Exception as e:
        log.debug(f"Facebook chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Instagram (verejne profily)
# ---------------------------------------------------------------------------

def find_on_instagram(company_name: str) -> list[str]:
    search_url = f"https://www.google.com/search?q=site:instagram.com+{quote(company_name)}+email"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/url?q=" in href:
                actual = href.split("/url?q=")[1].split("&")[0]
                if "instagram.com" in actual:
                    emails = scrape_emails_from_url(actual, follow_contact=False)
                    if emails:
                        log.info(f"Instagram: {emails[0]}")
                        return emails
    except Exception as e:
        log.debug(f"Instagram chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# LinkedIn (verejne profily firiem)
# ---------------------------------------------------------------------------

def find_on_linkedin(company_name: str) -> list[str]:
    search_url = f"https://www.google.com/search?q=site:linkedin.com/company+{quote(company_name)}+email+kontakt"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/url?q=" in href:
                actual = href.split("/url?q=")[1].split("&")[0]
                if "linkedin.com/company" in actual:
                    emails = scrape_emails_from_url(actual, follow_contact=False)
                    if emails:
                        log.info(f"LinkedIn: {emails[0]}")
                        return emails
    except Exception as e:
        log.debug(f"LinkedIn chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Web firmy - priame hladanie
# ---------------------------------------------------------------------------

def find_on_company_website(company_name: str, domain: str = None) -> list[str]:
    """Hlada email priamo na webe firmy cez Google."""
    if domain:
        url = f"https://{domain}"
        emails = scrape_emails_from_url(url, follow_contact=True)
        if emails:
            log.info(f"Web firmy: {emails[0]}")
            return emails

    search_url = f"https://www.google.com/search?q={quote(company_name)}+email+kontakt&num=5"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/url?q=" in href:
                actual = href.split("/url?q=")[1].split("&")[0]
                if actual.startswith("http") and not any(
                    skip in actual for skip in ["google", "facebook", "instagram", "linkedin", "tiktok"]
                ):
                    emails = scrape_emails_from_url(actual, follow_contact=True)
                    if emails:
                        log.info(f"Web (Google): {emails[0]}")
                        return emails
    except Exception as e:
        log.debug(f"Web firmy chyba: {e}")
    return []


# ---------------------------------------------------------------------------
# Hlavna funkcia - prehladá všetky zdroje paralelne
# ---------------------------------------------------------------------------

def find_email(company_name: str, country: str = "SK", domain: str = None) -> str:
    """
    Prehľadá všetky dostupné zdroje a vráti prvý nájdený email.
    company_name: názov firmy
    country: SK alebo CZ
    domain: ak je známa doména webu firmy
    """
    log.info(f"Hľadám email pre: {company_name} ({country})")

    sk_sources = [
        lambda: find_on_orsr(company_name),
        lambda: find_on_zivnostensky(company_name),
        lambda: find_on_firmy_sk(company_name),
        lambda: find_on_zlatestranky_sk(company_name),
        lambda: find_on_najfirmy(company_name),
        lambda: find_on_zoznam(company_name),
        lambda: find_on_mojedelo(company_name),
        lambda: find_on_heureka(company_name, "SK"),
        lambda: find_on_pricemania(company_name),
        lambda: find_on_favi(company_name),
        lambda: find_on_europages(company_name, "SK"),
        lambda: find_on_facebook(company_name),
        lambda: find_on_instagram(company_name),
        lambda: find_on_linkedin(company_name),
        lambda: find_on_company_website(company_name, domain),
    ]

    cz_sources = [
        lambda: find_on_ares(company_name),
        lambda: find_on_justice(company_name),
        lambda: find_on_firmy_cz(company_name),
        lambda: find_on_zlatestranky_cz(company_name),
        lambda: find_on_heureka(company_name, "CZ"),
        lambda: find_on_europages(company_name, "CZ"),
        lambda: find_on_facebook(company_name),
        lambda: find_on_instagram(company_name),
        lambda: find_on_linkedin(company_name),
        lambda: find_on_company_website(company_name, domain),
    ]

    sources = sk_sources if country == "SK" else cz_sources

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fn): fn for fn in sources}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    # Zrusi ostatne tasky
                    for f in futures:
                        f.cancel()
                    return result[0]
            except Exception as e:
                log.debug(f"Zdroj zlyhal: {e}")

    log.info(f"Email pre '{company_name}' sa nepodarilo nájsť")
    return ""


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("Použitie: python email_finder.py 'Názov firmy' [sk|cz]")
        sys.exit(1)

    name = sys.argv[1]
    country = sys.argv[2].upper() if len(sys.argv) > 2 else "SK"
    email = find_email(name, country)
    if email:
        print(f"\nNájdený email: {email}")
    else:
        print("\nEmail sa nenašiel")
