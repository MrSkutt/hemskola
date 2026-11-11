# Teknik
Hur saker fungerar och hur man bygger dem: maskiner, konstruktioner, material, el, styrning, datorer och programmering.

## Från idé till produkt
Teknikutveckling följer ofta samma steg och man går gärna flera varv:
1. Hitta ett **behov** eller problem
2. Hitta på **idéer** och välj en
3. Rita **skisser** och ritningar
4. Bygg en **modell** eller prototyp
5. **Testa** och utvärdera
6. **Förbättra** och bygg om
> En produkts **livscykel** går från råvara till tillverkning, användning och till sist återvinning eller avfall. Bra teknik tänker på hela vägen.

## Enkla maskiner
Enkla maskiner hjälper oss att göra ett arbete med mindre kraft. Men vinner man kraft så får man ta en längre väg: **arbetet blir detsamma**.
| Maskin | Hur den hjälper | Exempel |
|---|---|---|
| Spak | vrids kring en vridpunkt | sax, kofot, gungbräda, skottkärra |
| Lutande plan | längre väg med mindre kraft | ramp, backe, kil, skruv |
| Hjul och axel | stort hjul vrider en liten axel | ratt, skruvmejsel, cykel |
| Block (trissa) | ändrar kraftens riktning, flera block ger mindre kraft | kran, flaggstång |
| Kugghjul | för över och ändrar rörelse | cykelns växlar, klockor |
= Moment | M = F · l (kraft gånger avstånd från vridpunkten, enhet Nm)
= Spaklagen | F₁ · l₁ = F₂ · l₂ (spaken är i balans när momenten är lika stora)
= Hydraulik | F₁ / A₁ = F₂ / A₂ (trycket är lika i hela vätskan, används i bilbromsar och domkrafter)
Exempel: en kofot är 1,0 m lång och vridpunkten ligger 0,1 m från den korta änden. Man trycker 100 N på den långa änden (0,9 m från vridpunkten). Då blir kraften i den korta änden F = 100 · 0,9 / 0,1 = 900 N.

## Kugghjul och utväxling
= Utväxling | i = antal kuggar på drivet hjul / antal kuggar på drivande hjul
När ett litet kugghjul driver ett stort snurrar det stora **långsammare men med större kraft**. Driver ett stort hjul ett litet blir det tvärtom: **snabbare men svagare**. Hjul som greppar in i varandra snurrar åt motsatta håll.
Exempel: ett hjul med 10 kuggar driver ett med 30 kuggar. Utväxlingen är 30 / 10 = 3, så det stora hjulet snurrar tre gånger långsammare.
> På en cykel ger ett stort drev fram och ett litet bak hög hastighet men det blir tungt att trampa. Det är bra på plan mark. Uppför backar använder man en lägre växel.

## Konstruktioner och stabilitet
Krafter som verkar på konstruktioner:
| Kraft | Betyder | Exempel |
|---|---|---|
| Tryck | delar trycks ihop | pelare, bordsben |
| Drag | delar dras isär | rep, vajer i hängbro |
| Böjning | trycks på ena sidan och dras på andra | balk, hoppbräda |
| Vridning | roteras | skruvmejsel, axel |
| Skjuvning | skärs av | sax, bult som klipps av |
**Triangeln** är en stabil form eftersom den inte kan skeva sig. Därför används den i broar, master och tak (fackverk). Rektanglar kan trycka ihop sig till parallellogram om de inte stagas upp. En låg tyngdpunkt och en bred bas gör att något står stadigt.
Några brotyper: **balkbro** (enkel balk), **bågbro** (bågen leder krafterna ned i fundamenten), **hängbro** (kablar bär vägbanan) och **snedkabelbro**.

## Material
| Material | Egenskaper | Används till |
|---|---|---|
| Trä | lätt, förnybart, bra att bearbeta | hus, möbler |
| Stål | hårt och starkt, rostar utan skydd | broar, bilar, verktyg |
| Aluminium | lätt, rostar inte | flygplan, burkar |
| Koppar | leder ström bra | elkablar |
| Plast | lätt, formbar, kan vara billig | förpackningar, leksaker |
| Glas | hårt och genomskinligt, men sprött | fönster, glasfiber |
| Betong | tål tryck, tål dåligt drag (armeras med stål) | hus och broar |
| Keramik | hård och tål värme | muggar, kakel |
| Kolfiber | mycket lätt och starkt | cyklar, racerbilar |
**Termoplast** går att smälta om (till exempel PET-flaskor). **Härdplast** går inte att smälta om. **Komposit** är ett material som består av flera ämnen och som är bättre än de ingående delarna.
> Några begrepp: *hårdhet* (motstår repor), *seghet* (tål slag utan att gå sönder), *elasticitet* (går tillbaka efter böjning), *sprödhet* (går sönder utan att böjas).

## El och elektronik
![krets.svg](Krets: A batteri, B strömbrytare (här öppen), C motstånd, D lampa)
| Komponent | Gör |
|---|---|
| Batteri | är strömkälla, ger spänning |
| Strömbrytare | slår av och på strömmen |
| Lampa | lyser när det går ström |
| Motstånd | begränsar strömmen |
| Ledning | leder strömmen mellan komponenterna |
| Diod (LED) | släpper bara ström åt ett håll |
= Ohms lag | U = R · I
= Effekt | P = U · I
= Seriekoppling | en enda slinga. Går en komponent sönder slocknar allt
= Parallellkoppling | flera grenar. Lamporna lyser även om en går sönder
Strömmen går bara om kretsen är **sluten**. En **kortslutning** uppstår när strömmen får en väg med nästan inget motstånd, och då kan ledningarna bli mycket varma.
> **Likström** (batterier) går alltid åt samma håll. **Växelström** (vägguttaget) svänger fram och tillbaka 50 gånger per sekund (50 Hz). Experimentera aldrig med vägguttag.

## Styrning och automation
Många maskiner styrs automatiskt av tre delar:
| Del | Uppgift | Exempel |
|---|---|---|
| Sensor | mäter något | temperatur, ljus, avstånd, tryck |
| Styrenhet | bestämmer vad som ska göras | mikrodator (Arduino, micro:bit) |
| Aktuator | utför arbetet | motor, lampa, högtalare, ventil |
En **termostat** mäter temperaturen och slår av eller på värmen. Det kallas **återkoppling** när resultatet mäts och styr systemet vidare. En **robot** är en maskin som kan sköta uppgifter själv genom sensorer, styrning och rörelser.

## Datorer
| Del | Uppgift |
|---|---|
| Processor (CPU) | datorns "hjärna" som utför beräkningar |
| Arbetsminne (RAM) | snabbt minne för det som används just nu, töms när datorn stängs av |
| Lagring (SSD, hårddisk) | sparar filer permanent |
| Grafikkort (GPU) | räknar fram bilder, bra på spel och AI |
| Moderkort | kopplar ihop alla delar |
| Operativsystem | programmet som styr datorn (Windows, macOS, Android, Linux) |
**Hårdvara** är det man kan ta på. **Mjukvara** är programmen.
### Binära tal
Datorer använder bara **0 och 1** (bitar). Varje plats har ett värde som är dubbelt så stort som platsen till höger: 128, 64, 32, 16, 8, 4, 2, 1.
| Decimalt | Binärt |
|---|---|
| 0 | 0 |
| 1 | 1 |
| 2 | 10 |
| 3 | 11 |
| 4 | 100 |
| 5 | 101 |
| 8 | 1000 |
| 10 | 1010 |
| 13 | 1101 |
| 16 | 10000 |
Exempel: 1101 = 8 + 4 + 0 + 1 = 13.
### Datastorlekar
| Enhet | Storlek | Ungefär |
|---|---|---|
| 1 bit | 0 eller 1 | minsta enheten |
| 1 byte (B) | 8 bitar | en bokstav |
| 1 kilobyte (kB) | 1 000 B | en kort text |
| 1 megabyte (MB) | 1 000 kB | ett foto eller en sång |
| 1 gigabyte (GB) | 1 000 MB | en film |
| 1 terabyte (TB) | 1 000 GB | tusen filmer |
> Nätets hastighet anges i **bitar** per sekund (Mbit/s). Filers storlek anges i **byte**. Dela med 8 för att få MB per sekund: 100 Mbit/s ≈ 12,5 MB/s.

## Internet och säkerhet
| Begrepp | Betyder |
|---|---|
| IP-adress | nummer som identifierar en enhet på nätet |
| Router | skickar data mellan nätverk, ofta med wifi |
| Server | dator som lagrar sidor och tjänster |
| Domän / DNS | namn (som skolverket.se) som översätts till IP-adress |
| HTTPS | krypterad förbindelse (hänglås i webbläsaren) |
| Molnet | datorer hos någon annan där du lagrar saker |
**Säkra dig:**
- Använd långa lösenord, helst en lång fras, och olika på olika ställen
- Slå på tvåfaktorsinloggning där det går
- Klicka inte på länkar eller bilagor från okända (nätfiske, "phishing")
- Tänk efter innan du delar bilder och personuppgifter. Sånt som läggs ut är svårt att få bort
- Uppdatera program regelbundet

## Programmering
En **algoritm** är en steg-för-steg-instruktion för att lösa en uppgift. Ett **program** är en algoritm som en dator kan köra. Några grundbegrepp:
| Begrepp | Betyder | Exempel |
|---|---|---|
| Variabel | namngiven plats för ett värde | `poäng = 0` |
| Villkor | gör något bara om något är sant | `if poäng > 10:` |
| Loop | upprepar | `for i in range(5):` |
| Funktion | återanvändbar kodbit | `def hälsa(namn):` |
| Lista | flera värden samlade | `[3, 5, 8]` |
**Buggar** är fel i programmet och att **debugga** är att leta upp och rätta dem. Exempel på programspråk: Python, Scratch (blockprogrammering), JavaScript (webbsidor) och C++ (spel).
