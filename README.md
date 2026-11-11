# Hemskola

Ett litet webbaserat övningssystem för hemmabruk: eleven gör ett inledande test, övar i sin egen takt
på en nivå som anpassar sig, och gör statusprov då och då. Admin ser resultat och lägger in nya övningar.

* Ämnen från start: **matematik** och **svenska** (50 övningar vardera, nivå 1–5, ungefär åk 4–9)
* Backend: Python / FastAPI, databas: SQLite, webbserver: nginx, allt i Docker
* Inloggning med rollerna **admin** och **elev** (flera elever går bra)

## Kom igång

```bash
cp .env.example .env        # sätt ADMIN_PASSWORD
docker compose up -d --build
```

Öppna `http://servern:8080`, logga in som admin och skapa elever under **Användare**.
Databasen ligger i `./data/hemskola.db`. De 100 startövningarna läggs in automatiskt första gången.

Om du inte sätter `ADMIN_PASSWORD` skapas ett slumpmässigt lösenord som skrivs i loggen
(`docker compose logs app`).

### Köra utan Docker (test)

```bash
pip install -r requirements-dev.txt
ADMIN_PASSWORD=hemligt uvicorn app.main:app --reload
pytest
```

## Så fungerar det

| Del | Beskrivning |
|---|---|
| Inledande test | 2 frågor per nivå (10 totalt). Uppskattad nivå = högsta nivån där hon klarar minst hälften, i följd uppifrån och ned. Sätter startnivån. |
| Övning | Mestadels frågor på nuvarande nivå, ibland repetition av tidigare missade frågor och nivån under. Direkt återkoppling med förklaring. |
| Nivåbyte | Av de senaste 6 svaren på nivån: **5 rätt eller fler → upp**, **2 rätt eller färre → ner**. Därefter börjar ett nytt fönster. |
| Statusprov | Samma upplägg som det inledande testet. Rätt svar visas först efteråt. Kan höja nivån men sänker den aldrig. Resultaten sparas så att utvecklingen syns. |
| Admin | Översikt över alla elever, detaljvy med utveckling per dag, svaga områden, prov och senaste svar. Du kan sätta nivå manuellt. |

Eleven ser bara "Nivå 1–5". Kopplingen till ungefärlig årskurs visas bara för admin.

## Lägg in fler övningar

Under **Importera** klistrar du in eller laddar upp JSON. Be Claude generera i det här formatet:

```json
[
  {
    "subject": "matte",
    "topic": "Procent",
    "level": 3,
    "type": "text",
    "question": "Hur mycket är 10 % av 350?\nSvara endast med talet.",
    "answer": "35",
    "explanation": "10 % är en tiondel: 350 : 10 = 35."
  },
  {
    "subject": "svenska",
    "topic": "Ordklasser",
    "level": 2,
    "type": "mc",
    "question": "Vilket ord är ett adjektiv?",
    "options": ["springa", "snabb", "bord", "under"],
    "answer": "snabb",
    "explanation": "Adjektiv beskriver hur något är."
  }
]
```

* `type`: `mc` (flerval, `answer` måste finnas i `options`) eller `text` (fritext)
* `answer` kan vara en lista med flera godkända svar, t.ex. `["20:15", "20.15"]`
* Tal jämförs som tal: `4,25` och `4.25` är samma sak, `1/2` räknas som `0,5` och `%` ignoreras
* Nya ämnen (t.ex. `engelska`) dyker upp automatiskt hos eleven
* Samma ämne och samma frågetext läggs bara in en gång

Exempel på prompt: *"Skapa 25 övningar i matte, nivå 3, området bråk, i det här JSON-formatet. Blanda flerval och fritext."*
Tips: be om minst 20–30 övningar per nivå, så att samma frågor inte kommer för ofta. **Exportera** gärna
befintliga övningar och klistra in som exempel, så att nya får samma stil. Granska gärna nya övningar
innan eleven får dem, särskilt facit.

## Genererade övningar, ordlista, bilder och diagram

**Oändliga övningar.** Förutom de vanliga övningarna finns *generatorer*: små program som skapar en ny fråga med slumptal
(matte nivå 1–5: addition, bråk, procent, ekvationer, klockan, area, stapeldiagram, koordinater, rötter m.m.) eller slumpade ord
(svenska: ordklasser, böjning av verb/substantiv/adjektiv, en/ett, motsatser, synonymer). Varje gång eleven får en genererad fråga
sparas den, så att svaret kan rättas och visas i elevens historik. De räknas som vanliga övningar i nivåsystemet och proven.
Under **Övningar** visas `+ n ∞` för generatorer. Nya generatorer läggs i `app/generators.py` och `app/generators_sv.py`.

**Ordlista.** Under **Ord** ser du ordlistan som driver de svenska generatorerna. Fler ord läggs in via **Importera**:

```json
{"words": [{"word": "cykla", "pos": "verb", "level": 1, "forms": {"presens": "cyklar", "preteritum": "cyklade"}}]}
```

Ordklasser: verb, substantiv, adjektiv, adverb, preposition, pronomen, konjunktion, subjunktion, interjektion, räkneord.
En fil kan ha både `exercises` och `words`: `{"exercises": [...], "words": [...]}`. Dölj ord som ger konstiga frågor med knappen **Dölj**.

**Bilder.** Under **Bilder** laddar du upp png, jpg, gif, webp eller svg (högst 3 MB, svg med script avvisas). Filerna ligger i `data/media`.
Koppla en bild till en övning med `"image": "filnamn.png"` i importen.

**Diagram.** En övning kan ha ett `"diagram"` som ritas som SVG, utan bildfiler. Typer: `bar_chart`, `pie_chart`, `clock`, `fraction`,
`rectangle`, `right_triangle`, `number_line`, `coordinate`, `angle`. Exempel:

```json
{"subject": "matte", "topic": "Diagram", "level": 1, "type": "text", "question": "Vilken dag lånades flest böcker?",
 "answer": "Tor", "diagram": {"type": "bar_chart", "title": "Utlånade böcker", "labels": ["Mån", "Tor"], "values": [5, 12]}}
```

Uppgraderar du en befintlig installation läggs de nya tabellerna och kolumnerna till automatiskt, utan att data försvinner.

## Ämnen

Matte och svenska har generatorer. **Engelska** har generatorer för glosor (engelska ↔ svenska, nivå 1–5) och oregelbundna verb,
som hämtar ord ur ordlistan (ordklass `glosa`, se `app/seed/words_en.json`). Lägg till fler glosor så här:

```json
{"words": [{"word": "bicycle", "pos": "glosa", "level": 2, "sv": ["cykel"]},
           {"word": "wake", "pos": "glosa", "level": 3, "sv": ["vakna"], "forms": {"past": "woke", "pastpart": "woken"}}]}
```

Det finns 12 ämnen: matte, svenska, engelska, K-pop, de naturorienterande **biologi, fysik, kemi och teknik** samt de samhällsorienterande
**geografi, historia, religionskunskap och samhällskunskap** (ämnesnamn i importen: `biologi`, `fysik`, `kemi`, `teknik`, `geografi`, `historia`,
`religionskunskap`, `samhallskunskap`). Äldre installationer hade samlingsämnena `no` och `so`: vid uppgradering flyttas deras övningar, svar och
nivåer automatiskt till de nya ämnena. Startövningar finns i `app/seed/*.json`, bland annat med diagram och med de medföljande
exempelbilderna i `app/seed/media/` (de kopieras till `data/media` vid start, och befintliga filer skrivs aldrig över).
Nya ämnen skapas automatiskt: importera övningar med t.ex. `"subject": "engelska"`. Egna visningsnamn läggs i `SUBJECT_LABELS` i `app/logic.py`.

## K-pop

Ämnet **K-pop** (`"subject": "kpop"`) har 59 frågor om grupper, fans, historia, koreanska och hangul, plus matteuppgifter med konserter, streams och biljetter.
Det finns även generatorer för koreanska glosor (ordklass `koreanska`, se `app/seed/words_kpop.json`): koreanska → svenska, svenska → koreanska
och att läsa hangul. Bilderna (lightstick, scen, hangul, flagga) är egenritade SVG-filer i `app/seed/media/`. Inga fotografier av artister används.
Fakta om grupper ändras med tiden, så granska gärna frågorna ibland. Lägg till ord så här:

```json
{"words": [{"word": "jjang", "pos": "koreanska", "level": 4, "hangul": "짱", "sv": ["bäst, toppen"]}]}
```

## Rapport till skolan

På varje elevs sida i admin finns **Rapport att visa skolan**. Välj period (7, 30, 90 dagar eller hela tiden) och öppna en PDF med
antal frågor, andel rätt, aktivitet per dag/vecka, nivå och prov per ämne, områden som behöver övas, områden som går bra
och exempel på senaste felsvar. Nivåerna är en uppskattning från övningsprogrammet och inget betyg. PDF:en skapas med reportlab.

## Drift

* **Backup:** `sqlite3 data/hemskola.db ".backup data/backup-$(date +%F).db"` (eller kopiera `data/` medan appen står still).
* **Åtkomst utanför hemnätet:** lägg HTTPS framför (egen reverse proxy, Caddy/Traefik eller certbot) och sätt `COOKIE_SECURE=1` i `.env`.
  Utan HTTPS bör sidan bara nås i hemnätet eller via VPN.
* **Port:** ändra `8080:80` i `docker-compose.yml`, eller ta bort `ports` om en annan proxy kopplas till nginx-containern.
* Inloggningen stoppar efter 10 felaktiga försök per IP-adress och 10 minuter. Lösenord lagras med scrypt.
* Sidan har ingen CSRF-token utan förlitar sig på `SameSite=Lax` på sessionskakan, vilket räcker för hemmabruk.

## Idéer framåt

* Fler övningar per nivå i de nya ämnena, och generatorer för NO/SO
* Eget val av område att öva på, mål per dag, och belöningar/poäng
* Fler generatorer och fler ord i ordlistan, t.ex. engelska glosor
* Påminnelser/veckorapport till admin
