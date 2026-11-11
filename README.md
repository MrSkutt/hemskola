# Hemskola

Ett litet webbaserat övningssystem för hemmabruk: eleven gör ett inledande test, övar i sin egen takt
på en nivå som anpassar sig, och gör statusprov då och då. Admin ser resultat och lägger in nya övningar.

* 12 ämnen från start (matte, svenska, engelska, K-pop och åtta NO/SO-ämnen), nivå 1–5, ungefär åk 4–9: drygt 1 200 färdiga frågor plus generatorer som skapar nya
* Backend: Python / FastAPI, databas: SQLite, webbserver: nginx, allt i Docker
* Inloggning med rollerna **admin** och **elev** (flera elever går bra)

## Kom igång

```bash
cp .env.example .env        # sätt ADMIN_PASSWORD
docker compose up -d --build
```

Öppna `http://servern:8080`, logga in som admin och skapa elever under **Användare**.
Databasen ligger i `./data/hemskola.db`. Startövningarna läggs in automatiskt första gången, och nya läggs till vid uppgradering utan att befintlig data påverkas.

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
| Fakta | Fliken **Fakta** har en faktasida per ämne med grunder, formler, tabeller och bilder (se nedan). Fliken med övningar heter **Övningar**. |
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
Varje ämne har ungefär 20–35 färdiga frågor per nivå, och en del av dem använder bilder eller diagram (stapel, cirkel, tidslinje, klocka).
Filer som heter `<ämne>_2.json` är de utökade frågeuppsättningarna. NO/SO-ämnena har även generatorer (`app/generators_no.py`): grundämnen och
formler, densitet och Ohms lag, binära tal, huvudstäder, årtal, moms, ränta och mycket annat, där svaret räknas ut i kod.
Nya ämnen skapas automatiskt: importera övningar med t.ex. `"subject": "engelska"`. Egna visningsnamn läggs i `SUBJECT_LABELS` i `app/logic.py`.

### Ämnesgrupper och ämnesval per elev

Startsidan och adminvyerna delar in ämnena i grupper: *Grundämnen* (matte, svenska, engelska), *Naturorienterande ämnen (NO)*,
*Samhällsorienterande ämnen (SO)* och *Fritid och skoj* (K-pop). Ämnen du skapat själv hamnar under *Övrigt*. Grupperna ligger i
`SUBJECT_GROUPS` i `app/logic.py`.

Under **Elever → en elev** finns rutan **Ämnen för eleven** med två val per ämne:

* **Visas för eleven**: avstängda ämnen syns inte på elevens startsida och kan inte övas eller provas. Redan gjorda svar och nivåer sparas.
* **Med i rapporten**: styr vilka ämnen som tas med i PDF-rapporten (även antal svar, andel rätt och dagar i rad räknas bara på dessa).
  Fritidsämnen som K-pop är som standard *inte* med i rapporten. Vill du ändra rapporten bara en gång kan du bocka i eller ur ämnen under
  *Ämnen i rapporten* i rapportrutan, utan att ändra elevens inställning.

Rutorna vid gruppnamnen slår på eller av hela gruppen. Nya elever och nya ämnen får standardvalen (allt visas, allt utom fritidsämnen
är med i rapporten). Valen sparas i tabellen `user_subjects`, som läggs till automatiskt vid uppgradering.

## Fakta

Fliken **Fakta** bredvid **Övningar** har en sida per ämne: grunder och sedan lite mer som är bra att kunna. Matte har räkneordning, bråk,
procent, geometri, formler och grafer. Kemi har atomen och hela periodiska systemet med alla 118 grundämnen (bilden `periodiska_hela.svg`),
tabeller över vanliga grundämnen och formler, syror och baser, reaktionsformler och mol. Fysik, biologi, teknik, geografi, historia,
religionskunskap, samhällskunskap, svenska, engelska och K-pop/BTS (med hangul och glosor) har också egna sidor.

* Varje ämneskort på **Övningar** har en länk *📖 Fakta om …*, och under pågående övning finns samma länk (öppnas i ny flik).
  Länken finns **inte** i inledande test och statusprov, så provet mäter vad eleven kan utan hjälp.
* Eleven ser faktasidorna för de ämnen som är påslagna för henne (*Visas för eleven*, se ovan). Admin ser alla.
* Sidorna går att skriva ut (**Skriv ut**-knappen), och bilder öppnas i full storlek när man klickar på dem.
* Innehållet är skrivet med utgångspunkt i åk 4–9, men fakta ändras med tiden (årtal, folkmängder, vem som styr). Läs gärna igenom sidorna ibland.

**Så ändrar du innehållet:** varje sida är en textfil i `app/facts/<ämne>.md` (t.ex. `matte.md`). Vill du ändra utan att bygga om containern
lägger du en fil med samma namn i mappen `facts` bredvid databasen, alltså `data/facts/matte.md`. Den används då i stället för den
inbyggda och läses om automatiskt när filen ändras. En ny fil, t.ex. `data/facts/ritkonst.md`, ger en ny faktasida för ett ämne med det namnet.
Ämnesnamnet får bara innehålla `a-z`, `0-9` och `_`.

Filformatet är en liten delmängd av markdown:

```markdown
# Rubrik för sidan
Första stycket är ingressen som visas på översiktssidan.

## Ett avsnitt                      (### ger en underrubrik)
Vanlig text med **fet**, *kursiv* och `kod`.
- punktlista            1. numrerad lista
| Kolumn 1 | Kolumn 2 |            (första raden är rubriker, raden |---|---| ignoreras)
| a | b |
= A = b · h | Rektangelns area      (formelruta, flera rader efter varandra grupperas)
![solsystemet.svg](Bildtext)        (bild från mediamappen, se Bilder i admin)
@diagram {"type": "angle", "degrees": 60}   (diagram, samma format som i övningarna)
> Tips eller extra viktig information
```

## Områden, dagsmål, poäng, märken och belöningar

Det här är till för motivationen. **Allt går att slå av per elev** under **Elever → en elev → Dagsmål, poäng och belöningar**.
Bara skolämnen räknas, alltså inte fritidsämnen som K-pop.

* **Välja område:** på varje ämneskort kan eleven välja ett område att öva på (till exempel *Geometri* eller *Bråk, decimaltal och procent*)
  eller *Mitt svagaste område*. Svar i ett valt område räknas för nivån precis som vanligt. Frågornas många små områdesnamn grupperas i
  större områden i `app/areas.py`. Nya områdesnamn från egna importer hamnar i *Övrigt* tills du lägger in dem där.
* **Dagsmål:** admin sätter antal svar per dag (standard 15, 0 = inget mål). Svar i prov räknas också. Eleven ser en mätare på Övningar.
* **Poäng:** 10 poäng per rätt svar i övning (högst 15 rätta per ämne och dag, så att man inte kan pumpa ett ämne), 20 poäng när dagsmålet nås,
  50 extra för varje vecka i rad och 50 när eleven själv tar sig upp en nivå. Prov och K-pop ger inga poäng. Poäng räknas från den dag
  funktionen först användes för eleven, medan märken räknas på allt som gjorts.
* **Belöningar:** du lägger in belöningar med ett poängpris (t.ex. *Bio-kväll, 500 poäng*). Eleven ser hur långt hon har kvar. När poängen
  räcker markerar du belöningen som *utdelad* och dess poäng dras av. *Ångra* ger tillbaka poängen.
* **Märken:** 19 märken (första svaret, 100/500/1000 svar, dagar i rad, dagsmål, 5 och 10 rätt i rad, nivåer, prov med mera) som visas
  på sidan **Framsteg**. De räknas ut från svaren och listan finns i `app/motivation.py`.

Nya tabeller (`user_prefs`, `goal_days`, `level_ups`, `rewards`) läggs till automatiskt vid uppgradering och ingen befintlig data ändras.
Nya elever och befintliga elever får standardvärdena (område på, dagsmål 15, poäng och märken på).

## K-pop

Ämnet **K-pop** (`"subject": "kpop"`) har ett par hundra frågor om grupper, fans, historia, koreanska och hangul, plus matteuppgifter med konserter, streams och biljetter.
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

* Fler generatorer för biologi och religionskunskap, och fler frågor per nivå
* Fler generatorer och fler ord i ordlistan, t.ex. engelska glosor
* Påminnelser/veckorapport till admin
