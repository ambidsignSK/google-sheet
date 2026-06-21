#!/usr/bin/env python3
"""Zobrazi emailove kontakty z hotel reportu roztriedene podla krajiny."""

import json
import glob
import sys
from urllib.parse import urlparse

# Nacitaj najnovsi report
reports = sorted(glob.glob("hotel_report_*.json"))
if not reports:
    print("Nenasiel sa ziadny hotel_report_*.json")
    sys.exit(1)

report_file = reports[-1]
print(f"Report: {report_file}\n")

with open(report_file, encoding="utf-8") as f:
    data = json.load(f)

buckets = {"sk": [], "cz": [], "at": [], "hu": [], "en": []}

for h in data["hotels"]:
    if h.get("status") not in ("dry_run", "sent"):
        continue
    email = h.get("email", "")
    lang = h.get("lang", "")
    url = h.get("url", "")
    region = h.get("region", "")

    # Urcenie krajiny
    if lang:
        country = lang
    else:
        domain = urlparse(url).netloc.lower()
        if domain.endswith(".sk"):
            country = "sk"
        elif domain.endswith(".cz"):
            country = "cs"
        elif domain.endswith(".at"):
            country = "at"
        elif domain.endswith(".hu"):
            country = "hu"
        else:
            country = "en"

    # Normalizacia
    country = {"cs": "cz", "de": "at"}.get(country, country)
    if country not in buckets:
        country = "en"

    buckets[country].append({"email": email, "url": url, "region": region})

labels = {
    "sk": "🇸🇰  SLOVENSKO",
    "cz": "🇨🇿  ČESKO",
    "at": "🇦🇹  RAKÚSKO / NEMECKO",
    "hu": "🇭🇺  MAĎARSKO",
    "en": "🌐  OSTATNÉ (EN)",
}

total = 0
for key, label in labels.items():
    contacts = buckets[key]
    if not contacts:
        continue
    print(f"{label}  ({len(contacts)}x)")
    print("-" * 52)
    for c in contacts:
        domain = urlparse(c["url"]).netloc or c["url"]
        print(f"  {c['email']:<38}  {domain}")
    print()
    total += len(contacts)

print(f"{'='*52}")
print(f"  Spolu: {total} emailových kontaktov")
