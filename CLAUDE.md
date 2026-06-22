# PPC Lead Agent - Claude rutiny

## Odoslať ponuku na email

Keď používateľ napíše emailovú adresu alebo povie "pošli ponuku na ...", spusti:

```bash
python agent.py <email>
```

Príklady spúšťania:
- "pošli ponuku na info@firma.sk" → `python agent.py info@firma.sk`
- "odošli na kontakt@spolocnost.cz" → `python agent.py kontakt@spolocnost.cz`
- Ak používateľ napíše len email ako "info@firma.sk" → `python agent.py info@firma.sk`

Po spustení informuj používateľa či bol email úspešne odoslaný.

## Spustiť agenta (hľadanie nových firiem)

Keď používateľ povie "spusti agenta" alebo "hľadaj nové firmy":

```bash
python agent.py
```

## Spustiť monitor odpovedí

Keď používateľ povie "skontroluj odpovede" alebo "spusti monitor":

```bash
python monitor.py
```

## Spustiť hotel backlink agenta

Keď používateľ povie "hľadaj hotely", "oslovi hotely" alebo "spusti hotel agenta":

```bash
python hotel_backlink_agent.py
```

Pre testovanie bez odosielania emailov:

```bash
python hotel_backlink_agent.py --dry-run
```

Agent hľadá hotely pri letiskách VIE (Viedeň), BTS (Bratislava), BUD (Budapešť), PRG (Praha) a BRQ (Brno), extrahuje emaily z ich webov a odosiela ponuku spolupráce (spätný odkaz) v jazyku danej krajiny (SK/CZ/DE/HU/EN).

## Testovanie emailov (hotel agent)

Keď používateľ povie "pošli test", "otestuj emaily" alebo "pošli preview":

```bash
python send_previews.py
```

Odošle 5 testovacích emailov (SK/CZ/DE/HU/EN) na ambidsign@gmail.com.

Pre konkrétny jazyk:

```bash
python preview_email.py sk
python preview_email.py cs
python preview_email.py de
python preview_email.py hu
python preview_email.py en
```

## Zobraziť emailové kontakty roztriedené podľa krajiny

```bash
python show_contacts.py
```

## Overiť Gmail nastavenie

```bash
python test_email.py
```

## Dôležité informácie

- Pracovný priečinok: `C:\Users\ambro\google-sheet\google-sheet`
- Ponuky sa odosielajú z: ambidsign@gmail.com
- `.sk` email → slovenský text, `.cz` email → český text
- Každý odoslaný email má BCC kópiu na ambidsign@gmail.com
- Automatické spúšťanie: 10:00 a 15:00 v pracovné dni (Task Scheduler)
