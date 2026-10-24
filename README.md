# 📡 Aksjeradar

Personlig verktøy som hver dag henter gratis markedsdata for aksjer i Norden og USA,
regner ut tekniske signaler, analytikerkonsensus, fundamentale nøkkeltall og innsidehandler,
rangerer alt til én score per aksje – og gir deg:

- **Mobil-app** for iPhone/Android – nå et rent **fondsverktøy**: daglig fondsrapport med
  innskuddsråd, estimert verdi av fondene dine akkurat nå, rangering av fond og logg (se punkt 6)
- **Daglig rapport** (Markdown + HTML) med topp-liste, idékategorier og varsler for aksjer
- **Telegram-melding** (eller e-post) med det viktigste, og **push-varsler** med dagens fondsråd
- **Dashboard** på PC-en med screener og detaljer per aksje

Datakilde: Yahoo Finance via biblioteket `yfinance` – gratis, ingen API-nøkkel.

> Dette er et analyseverktøy for personlig bruk, ikke investeringsråd. Signalene er mekaniske
> regler. Bruk dem som en liste å undersøke videre.

---

## 1. Installasjon (én gang)

Du trenger **Python 3.10 eller nyere** ([python.org/downloads](https://www.python.org/downloads/) –
huk av «Add Python to PATH» under installasjonen på Windows).

Åpne en terminal (Windows: «Ledetekst» / PowerShell, Mac: «Terminal») i mappen `aksjeradar` og kjør:

```bash
pip install -r requirements.txt
```

Det tar et par minutter første gang.

## 2. Prøv det med demo-data (ingen nettverk)

```bash
python run.py --demo
```

Dette lager en rapport med tilfeldige tall, slik at du ser hvordan alt ser ut. Åpne deretter dashboardet:

```bash
streamlit run dashboard.py
```

(Windows: dobbeltklikk `start_dashboard.bat`.) Nettleseren åpner `http://localhost:8501`.

## 3. Kjør med ekte data

```bash
python run.py
```

Første gang tar det 2–5 minutter (fundamentaldata hentes for hver aksje). Senere kjøringer er
raskere fordi fundamentaldata bufres i noen dager (`fundamentals_max_age_days` i `config.yaml`).

Resultatet:

- `reports/latest.html` – åpne i nettleseren
- `reports/aksjeradar_<dato>.md` – samme innhold som tekst
- `data/aksjeradar.db` – alt lagres her, dashboardet leser fra denne

Nyttige varianter:

```bash
python run.py --no-notify                 # ikke send Telegram/e-post
python run.py --refresh                   # hent fundamentaldata på nytt for alle
python run.py --tickers EQNR.OL,AAPL,NVDA # bare disse aksjene
```

## 4. Telegram-varsel (anbefalt, 5 minutter)

1. Åpne Telegram, søk opp **@BotFather**, send `/newbot` og følg instruksjonene. Du får et **token**.
2. Send en melding (hva som helst) til den nye boten din.
3. Åpne i nettleseren: `https://api.telegram.org/bot<TOKEN>/getUpdates` (bytt ut `<TOKEN>`).
   Finn `"chat":{"id":123456789` – det tallet er din **chat-id**.
4. Kopier `.env.example` til `.env` og fyll inn:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   TELEGRAM_CHAT_ID=123456789
   ```
5. Kjør `python run.py` – du får en melding med topp 5, ideer og varsler.

E-post fungerer på samme måte med `SMTP_*`-feltene i `.env` (Gmail krever «app-passord»).
Slå av/på i `config.yaml` under `notify:`.

## 4b. Push-varsler på mobilen (ntfy, to minutter)

1. Installer appen **ntfy** (gratis, App Store / Google Play).
2. Trykk **+** i ntfy og abonner på emnet som står i `config.yaml` under `notify.push.ntfy_topic`
   (står også i appen under Mer → Push-varsler, med kopier-knapp).
3. Tillat varsler. Du får dagens råd for fondene dine hver morgen, og varsel når rådet for et fond
   endres eller et fond skifter til/fra gunstig inngang. Varslene åpner appen når du trykker på dem. (Intradag-setups kan slås på med `notify.push.intraday: true`.)

Vil du holde emnet hemmelig (repoet er offentlig), legg det i stedet inn som GitHub-hemmelighet
`NTFY_TOPIC` (Settings → Secrets and variables → Actions) – den overstyrer `config.yaml`.

## 5. Kjør automatisk hver dag

Velg ett av alternativene:

**A) GitHub Actions (anbefalt – PC-en trenger ikke stå på, og mobil-appen oppdaterer seg selv)**
1. Opprett et repo på GitHub og last opp mappen (uten `.env`!). Velg *offentlig* repo hvis du vil ha
   mobil-appen gratis via GitHub Pages (repoet inneholder bare kode og en liste over børsnoterte aksjer –
   aldri Telegram-nøkkelen, den ligger i Secrets).
2. Repo → *Settings* → *Secrets and variables* → *Actions* → legg inn `TELEGRAM_BOT_TOKEN` og `TELEGRAM_CHAT_ID`.
3. Ferdig – `.github/workflows/daily.yml` kjører ved hver opplasting og hver ukedag kl. 08:40 (vintertid),
   sender Telegram og publiserer mobil-appen med ferske data. Test via *Actions* → *Run workflow*.

**B) Windows – Oppgaveplanlegging**
Søk «Oppgaveplanlegging» → *Opprett grunnleggende oppgave* → Daglig, kl. 08:30 →
*Start et program*: `kjor_analyse.bat` i denne mappen.

**C) Mac/Linux – cron**
```bash
crontab -e
# legg til (ukedager 08:30):
30 8 * * 1-5 cd /sti/til/aksjeradar && python3 run.py >> cron.log 2>&1
```

## 6. Mobil-app på iPhone (og Android) – fondsappen

Mappen `docs/` er en komplett mobil-app (web-app) som leser `docs/funds.json` (daglig fondsanalyse,
laget av `run.py`) og `docs/funds_now.json` (estimat hvert kvarter i børstiden, laget av
`intraday_run.py`). Appen er et rent **fondsverktøy** med fire faner:

- **I dag** – dagens fondsrapport for fondene du eier (`owned: true` under `funds.list` i
  `config.yaml`): ett kort per fond med innskuddsråd – **Ekstrainnskudd anbefales / Vurder
  ekstrainnskudd / Fortsett vanlig sparing / Avvent** – hovedgrunn, dagens endring og avstand fra topp.
  Trykk på kortet for den automatisk skrevne analysen (status, indeks og krone, trend, sektor/marked,
  risiko, konklusjon med forslag til størrelse, og konkrete nivåer for når rådet ville endret seg).
  Øverst vises summen av fondene dine akkurat nå, og nederst andre fond med gunstig inngang.
- **Verdi** – estimert verdi av fondene dine akkurat nå: du registrerer verdien fra banken og datoen,
  og appen regner videre med fondets kurve i NOK pluss dagens bevegelse i indeks-ETF-en × valutakurs,
  oppdatert hvert kvarter i børstiden. Verdiene lagres bare på telefonen (sikkerhetskopi under «Mer»).
- **Fond** – rangering av alle fondene i listen etter attraktivitet (inngang, trend, sektor/marked fra
  aksjeanalysen, risiko/prising), med nivå Gunstig/Svært gunstig/Nøytral/Dyr, graf og forklaring.
- **Mer** – logg over hvordan rådene har utviklet seg dag for dag, push-varsler, sikkerhetskopi og «Om».

Aksjeanalysen (score, anbefalinger, ideer) kjører fortsatt på serveren – fondsrangeringen bruker den for
sektor-/markedsbildet – og ligger i `docs/data.json` og dashboardet på PC-en, men vises ikke i appen.
Appen fungerer uten nett (viser siste data) og følger mørk/lys modus på telefonen.

**Publiser den (gratis, via GitHub Pages):**
1. Gjør punkt 5A over (GitHub-repo + Actions).
2. Repo → *Settings* → *Pages* → *Build and deployment*: Source **GitHub Actions**.
3. Etter første kjøring (3–5 min) er appen på `https://<brukernavn>.github.io/<repo-navn>/`
   (adressen står også under jobben *deploy* i *Actions*-fanen).
4. **På iPhone:** åpne adressen i Safari → trykk **Del**-ikonet → **«Legg til på Hjem-skjerm»**.
   Du får et eget ikon, og appen åpner i fullskjerm som en vanlig app.
   **Android:** åpne i Chrome → meny → «Legg til på startskjermen» / «Installer app».
5. Hver morgen etter at Actions har kjørt, trykker du bare oppdater-knappen i appen (eller åpner den på nytt).

**Prøve den lokalt først** (på PC-en, eller på telefonen via samme Wi-Fi):
```bash
python run.py --demo              # eller python run.py for ekte data
python -m http.server 8000 -d docs
```
Åpne `http://localhost:8000` på PC-en. På telefonen: finn PC-ens IP-adresse (Windows: `ipconfig`,
Mac: `ifconfig`) og åpne `http://<ip>:8000`. (Å dobbeltklikke `docs/index.html` direkte fungerer ikke
i alle nettlesere, fordi appen henter `funds.json` med en nettverksforespørsel.)

## 7. Tilpass

Alt styres fra `config.yaml`:

- **`universe`** – hvilke aksjer som følges. Legg til/fjern fritt. Yahoo-tickere:
  Oslo `.OL`, Stockholm `.ST`, København `.CO`, Helsinki `.HE`, USA uten suffiks.
  Med `universe_extra: sp500: true` hentes i tillegg hele S&P 500 fra Wikipedia ved hver kjøring
  (ca. 700 aksjer totalt). Fundamentaldata hentes for maks `max_details_per_run` aksjer per kjøring,
  de eldste først, så første kjøring med stort univers bruker 2–3 dager på å fylle alt.
- **`signals`** – perioder for RSI/SMA, terskel for volumhopp og utbrudd.
- **`scoring.weights`** – hvor mye teknisk / analytiker / fundamental / innsider skal telle.
- **`report`** – hvor mange aksjer som vises.
- **`export`** – hvor datafilen til mobil-appen legges, og hvor mange kursdager grafen viser.

## Slik beregnes scoren

| Delscore | Hva den måler |
|---|---|
| **Teknisk** | Kurs mot SMA50/SMA200, golden/death cross, MACD, RSI, utbrudd over 60-dagers topp, nærhet til 52-ukers topp, volumhopp, 6-måneders styrke relativt til universet |
| **Analytiker** | Yahoo-konsensus (1 = sterkt kjøp … 5 = selg), oppside til snittkursmål, opp-/nedgraderinger siste 90 dager (krever minst 3 analytikere) |
| **Fundamental** | P/E, forventet P/E, EV/EBITDA, PEG, P/B, gjeld/EK, omsetnings- og resultatvekst, marginer, egenkapitalavkastning, FCF-yield – rangert mot de andre aksjene |
| **Innsider** | Kjøp vs. salg (i kroner) blant innsidere siste 180 dager |

Samlet score = vektet snitt. Mangler en delscore (f.eks. ingen analytikere), teller den som nøytral 50,
slik at tynt datagrunnlag trekker mot midten i stedet for å gi toppscore.

**Anbefaling** (Sterkt kjøp / Kjøp / Hold / Avvent / Unngå) regnes ut fra scoren: ≥ 75 Sterkt kjøp, ≥ 65 Kjøp,
≥ 50 Hold, ≥ 40 Avvent, ellers Unngå. Kjøp krever at kursen er over SMA200. Death cross eller brudd under
SMA200 gir høyst Avvent; sterkt overkjøpt RSI (> 78), negative analytikere, kurs over analytikernes kursmål
eller flere nedgraderinger gir høyst Hold. Hver anbefaling vises med begrunnelse, risikonivå (daglig
svingning) og datagrunnlag. Reglene ligger i `recommend()` i `aksjeradar/scoring.py`.

**Idékategorier:** Momentum · Analytiker-oppside · Nylige oppgraderinger · Utbrudd / nær 52-ukers topp ·
Oversolgt kvalitet · Innsidekjøp. Pluss **Varsler** for aksjer som viser svakhet (nyttig for det du eier).
Reglene for hver kategori står i fanen «Om scoringen» i dashboardet og i `aksjeradar/scoring.py`.

## Begrensninger du bør kjenne til

- Yahoo-data er ca. 15 min forsinket og «uoffisielt» – yfinance kan slutte å virke når Yahoo endrer noe
  (oppdater med `pip install -U yfinance`).
- Analytikerdekning og innsidehandler er best for USA. For mindre nordiske selskaper er dekningen tynn,
  og innsidehandler mangler ofte. (Oslo Børs sitt Newsweb er et naturlig neste steg for norske innsidekjøp.)
- Signalene er ikke backtestet. Enkle tekniske regler alene har svak prediksjonskraft; verdien ligger i
  kombinasjonen og i at du får en kort liste å se nærmere på hver dag.

## Mappestruktur

```
aksjeradar/
├── run.py              # daglig kjøring (pipeline)
├── intraday_run.py     # kjøring hvert 15. min i børstiden: 15m-kurser til 1D-grafen og fondsestimatet
├── dashboard.py        # Streamlit-dashboard
├── config.yaml         # aksjer, terskler, vekter
├── .env.example        # mal for Telegram/e-post-hemmeligheter
├── requirements.txt
├── aksjeradar/
│   ├── config.py       # leser config.yaml og .env
│   ├── data.py         # henting fra Yahoo Finance + demo-data
│   ├── signals.py      # RSI, MACD, SMA, Bollinger, ATR, utbrudd
│   ├── scoring.py      # delscore, samlet score, idékategorier
│   ├── report.py       # Markdown / HTML / Telegram-tekst
│   ├── export.py       # skriver docs/data.json til mobil-appen
│   ├── notify.py       # Telegram og e-post
│   └── storage.py      # SQLite-database
│   ├── autotrader.py   # virtuell portefølje som følger anbefalingene automatisk (slått av i config.yaml)
│   ├── intraday.py     # 15m-kurser, fondsestimat (og intradag-setups – ikke vist i appen lenger)
│   ├── funds.py        # aksjefond: gunstige innganger (proxy-ETF × valuta)
│   ├── gurus.py        # kjente investorers 13F-porteføljer (slått av i config.yaml, kan slås på igjen)
│   ├── universe.py     # setter sammen universet (config + S&P 500 fra Wikipedia)
├── docs/               # mobil-appen (index.html, app.js, app.css, sw.js, ikoner) + funds.json, funds_now.json (og data.json/stocks/ for dashboardet)
├── data/               # databasen havner her
├── reports/            # rapportene havner her
└── .github/workflows/daily.yml   # automatisk kjøring på GitHub + oppdatering av appen
```
