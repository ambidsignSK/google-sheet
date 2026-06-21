# PPC Lead Agent - Claude rutiny

## Odoslať ponuku na email

Keď používateľ napíše emailovú adresu alebo povie "pošli ponuku na ...", použi Gmail MCP na vytvorenie draftu s kompletnou cenovou ponukou. Draft sa uloží do Gmailu a používateľ ho môže odoslať jedným klikom.

### Text emailu (SK - pre .sk domény)

**Predmet:** Cenová ponuka: PPC reklama pre Vašu novú firmu

```
Dobrý deň,

V dnešnej dobe je online viditeľnosť kľúčová pre rýchly rast.
Ponúkame Vám profesionálnu správu PPC reklamy (Google Ads, Meta Ads), špeciálne navrhnutú pre nové firmy.

Čo získate?
• Nastavenie a správa Google Ads / Facebook & Instagram reklám
• Cielenie priamo na Vašich ideálnych zákazníkov
• Mesačné reporty a optimalizácia kampaní

Cenník správy:
• Štartér (rozpočet do 300 €/mes): 200 €/mes
• Business (rozpočet do 800 €/mes): 350 €/mes
• PRO (nad 800 €/mes): individuálna dohoda

Radi Vám pripravíme bezplatnú analýzu a konkrétny návrh kampane na mieru.

Neváhajte nás kontaktovať – odpovieme do 24 hodín.

S pozdravom

Tomáš Ambroz
@mbi design
+421 907 926 375

Web a Kampaň, ktoré zarábajú.
ambidesign.eu
```

### Text emailu (CZ - pre .cz domény)

**Predmet:** Cenová nabídka: PPC reklama pro Vaši novou firmu

```
Dobrý den,

V dnešní době je online viditelnost klíčová pro rychlý růst.
Nabízíme Vám profesionální správu PPC reklamy (Google Ads, Meta Ads), speciálně navržené pro nové firmy.

Co získáte?
• Nastavení a správa Google Ads / Facebook & Instagram reklamy
• Cílení přímo na Vaše ideální zákazníky
• Měsíční reporty a optimalizace kampaní

Ceník správy:
• Štartér (rozpočet do 300 €/měs): 200 €/měs
• Business (rozpočet do 800 €/měs): 350 €/měs
• PRO (nad 800 €/měs): individuální dohoda

Rádi Vám připravíme bezplatnou analýzu a konkrétní návrh kampaně na míru.

Neváhejte nás kontaktovat – odpovíme do 24 hodin.

S pozdravem

Tomáš Ambroz
@mbi design
+421 907 926 375

Web a Kampaň, ktoré zarábajú.
ambidesign.eu
```

### Pravidlá:
- `.sk` email → slovenský text
- `.cz` email → český text
- iná doména → slovenský text
- Vždy vytvor draft cez Gmail MCP nástroj `mcp__Gmail__create_draft`
- BCC: ambidsign@gmail.com

## Spustiť agenta na PC (hľadanie nových firiem)

Keď používateľ povie "spusti agenta" alebo "hľadaj nové firmy":

```bash
python agent.py
```

## Spustiť monitor odpovedí na PC

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
