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

## Dôležité informácie

- Pracovný priečinok: `C:\Users\ambro\google-sheet\google-sheet`
- Ponuky sa odosielajú z: ambidsign@gmail.com
- `.sk` email → slovenský text, `.cz` email → český text
- Každý odoslaný email má BCC kópiu na ambidsign@gmail.com
- Automatické spúšťanie: 10:00 a 15:00 v pracovné dni (Task Scheduler)
