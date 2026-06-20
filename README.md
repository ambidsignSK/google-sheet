# PPC Lead Agent - SK/CZ

Agent automaticky hľadá nové firmy zaregistrované v SR a ČR a posiela im cenovú ponuku na PPC reklamu.

## Ako to funguje

1. **Hľadá nové firmy** v Obchodnom registri SR (orsr.sk) a českom ARES
2. **Nájde email** z profilu firmy, kontaktnej stránky webu, alebo cez Google
3. **Odošle cenovú ponuku** na PPC reklamu (Google Ads, Meta Ads)
4. **Loguje odoslané emaily** aby neposielal duplicity

## Nastavenie

### 1. Inštalácia závislostí
```bash
pip install -r requirements.txt
```

### 2. Gmail App Password
Gmail neumožňuje priame SMTP heslo - treba vytvoriť App Password:
1. Choď na **myaccount.google.com → Security → 2-Step Verification**
2. Dole nájdi **App passwords**
3. Vytvor nové heslo pre "Mail" / "Windows Computer"
4. Skopíruj 16-znakové heslo

### 3. Konfigurácia `.env`
```bash
cp .env.example .env
```
Uprav `.env`:
```
GMAIL_ADDRESS=ambidsign@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # sem vlož App Password
DAYS_BACK=7       # hľadaj firmy za posledných 7 dní
EMAIL_DELAY=10    # 10 sekúnd medzi emailmi
```

## Spustenie

```bash
python agent.py
```

### Dry run (bez odosielania emailov)
Nechaj `GMAIL_APP_PASSWORD` prázdne v `.env` - agent nájde emaily ale neodošle ich, len ich zaloguje.

## Súbory

| Súbor | Popis |
|-------|-------|
| `agent.py` | Hlavný agent |
| `sent_emails.json` | Zoznam už odoslaných emailov (auto-generovaný) |
| `report_YYYYMMDD_HHMMSS.json` | Report z každého behu |
| `agent.log` | Log súbor |

## Automatické spúšťanie (cron)

Spúšťať každý deň o 9:00:
```bash
crontab -e
# Pridaj:
0 9 * * 1-5 cd /home/user/google-sheet && python agent.py
```

## Cenová ponuka

Agent posiela ponuku v slovenčine (SK firmy) alebo češtine (CZ firmy):
- Správa Google Ads / Meta Ads
- Starter: 149 €/mes
- Business: 249 €/mes  
- Pro: individuálne
- **Prvý mesiac ZADARMO** pri zmluve na 3 mesiace
