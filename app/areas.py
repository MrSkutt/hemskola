"""Områden att öva på. Frågornas egna områdesnamn (topic) är många och små, så de grupperas här i större områden
som eleven kan välja mellan. Okända områdesnamn (t.ex. från egna importer) hamnar i "Övrigt"."""

BILDER = "Bilder och diagram"
RAKNA = "Räkneuppgifter"
OVRIGT = "Övrigt"

# Gäller i alla ämnen
GLOBAL = {
    "Diagram": BILDER, "Picture": BILDER, "Titta på bilden": BILDER,
    "Räkna": RAKNA,
}

AREAS = {
    "matte": {
        "Tal och räkning": ["Tal", "Huvudräkning", "Avrundning", "Multiplikation", "Division", "Negativa tal",
                            "Potenser", "Räkneregler", "Enheter", "Tid", "Textuppgifter"],
        "Bråk, decimaltal och procent": ["Bråk", "Decimaltal", "Procent", "Förhållande", "Proportionalitet"],
        "Geometri": ["Area", "Geometri", "Vinklar", "Pythagoras", "Koordinatsystem"],
        "Algebra och ekvationer": ["Ekvationer", "Ekvationssystem", "Funktioner"],
        "Statistik och sannolikhet": ["Statistik", "Sannolikhet", "Kombinatorik"],
    },
    "svenska": {
        "Ord och ordklasser": ["Ordklasser", "Adjektiv", "Verb", "Verbformer", "Pronomen", "Ordböjning", "Frågeord",
                               "Synonymer", "Ordförråd", "Sammansatta ord", "Sär- och sammanskrivning"],
        "Stavning och skrivregler": ["Stavning", "Skrivregler", "Skiljetecken", "Alfabetet", "Att och och",
                                     "De och dem", "En och ett", "Vart och var"],
        "Meningar och grammatik": ["Meningar", "Meningstyper", "Satsdelar", "Ordföljd", "Aktiv och passiv"],
        "Läsa och skriva texter": ["Läsförståelse", "Texttyper", "Textbindning", "Argumentation", "Retorik",
                                   "Källkritik"],
        "Språk och uttryck": ["Bildspråk", "Ordspråk", "Rim", "Språkregister"],
    },
    "engelska": {
        "Grammatik": ["Grammar", "Grammatik", "Passiv", "Konditionalis", "Jämförelser", "Plural", "Ordklasser",
                      "Oregelbundna verb", "Indirekt fråga", "Prepositions"],
        "Ord och glosor": ["Vocabulary", "Ordförråd", "Glosor", "Motsatser", "Idioms", "Phrasal verbs", "Animals",
                           "Colours", "Days", "Family", "Numbers", "Greetings", "Hälsningar", "Time", "Klockan"],
        "Läsa": ["Reading"],
        "Engelska med K-pop": ["K-pop"],
    },
    "biologi": {
        "Celler och ärftlighet": ["Celler", "Genetik", "Evolution", "Mikrober"],
        "Människokroppen": ["Kroppen"],
        "Växter och djur": ["Växter", "Djur"],
        "Ekologi och miljö": ["Ekologi", "Näringskedjan", "Årstider"],
    },
    "fysik": {
        "Krafter och rörelse": ["Krafter", "Rörelse"],
        "Energi och värme": ["Energi", "Värme", "Temperatur", "Vatten"],
        "El": ["El", "Elektricitet"],
        "Ljus, ljud och vågor": ["Ljus", "Ljud", "Ljud och ljus", "Ljus och ljud", "Vågor"],
        "Rymden": ["Rymden", "Solsystemet"],
        "Atomer och material": ["Atomfysik"],
        RAKNA: ["Densitet", "Enheter"],
    },
    "kemi": {
        "Atomer och grundämnen": ["Atomer", "Grundämnen", "Periodiska systemet", "Jonbildning", "Molekyler",
                                  "Kemiska föreningar", "Bindningar"],
        "Reaktioner och eld": ["Reaktioner", "Eld", "Elektrokemi"],
        "Syror och baser": ["Syror och baser"],
        "Material och blandningar": ["Materia", "Material", "Blandningar", "Luft", "Kemi", "Miljö", "Organisk kemi"],
    },
    "teknik": {
        "Datorer och nätverk": ["Datorer", "Nätverk", "Mobilnät", "Datalagring", "Säkerhet", "Navigering"],
        "Programmering och logik": ["Programmering", "Logik", "Binärt", "Binära tal", "Styrteknik"],
        "El och elektronik": ["El", "Elektronik", "Energi", "Ljud"],
        "Konstruktion och material": ["Enkla maskiner", "Mekanik", "Konstruktion", "Material", "Ritningar", "Verktyg"],
        "Miljö och teknikhistoria": ["Miljö", "Teknikhistoria"],
    },
    "geografi": {
        "Kartor och tid": ["Kartor", "Tidszoner"],
        "Länder och städer": ["Länder och huvudstäder", "Länder och kontinenter", "Världen", "Sveriges grannar"],
        "Sverige": ["Sverige"],
        "Natur och klimat": ["Jorden", "Natur", "Vattnets kretslopp", "Miljö"],
        "Befolkning och ekonomi": ["Befolkning", "Ekonomi"],
        "Korea": ["Korea"],
    },
    "historia": {
        "Forntid och antiken": ["Forntiden", "Egypten", "Antiken"],
        "Medeltid och vikingar": ["Medeltiden", "Vikingar"],
        "Nyare tid": ["Upptäckter", "Industrialiseringen", "Världskrigen"],
        "Sveriges historia": ["Sverige"],
        "Världens historia": ["Världen", "Historia"],
        "Tid och källor": ["Tid", "Tidslinje", "Tidsräkning", "Årtal", "Källkritik"],
        "Korea": ["Korea"],
    },
    "religionskunskap": {
        "Kristendom": ["Kristendom"],
        "Islam": ["Islam"],
        "Judendom": ["Judendom"],
        "Hinduism och buddhism": ["Hinduism", "Buddhism"],
        "Religion i allmänhet": ["Världsreligionerna", "Heliga skrifter", "Gudshus", "Högtider", "Symboler", "Ledare"],
        "Etik och livsfrågor": ["Etik", "Filosofi", "Livsfrågor", "Livsåskådningar", "Tro", "Samhälle", "Sverige",
                                "Korea"],
    },
    "samhallskunskap": {
        "Demokrati och val": ["Demokrati", "Val", "Riksdagen", "Statskunskap", "Statsskick", "Styre"],
        "Lagar och rättigheter": ["Lag", "Lagar", "Rättigheter", "Mänskliga rättigheter", "Mobbning", "Gemenskap",
                                  "Skolan"],
        "Ekonomi och arbete": ["Ekonomi", "Arbete"],
        "Media och nätet": ["Media", "Medier", "Nätet"],
        "Sverige och världen": ["EU", "FN", "Sverige i världen", "Världen"],
    },
    "kpop": {
        "BTS": ["BTS"],
        "Grupper, bolag och fans": ["Grupper", "Bolag", "Fans", "Musik", "Konsert", "Scen", "Film", "Historia",
                                    "K-pop", "Korea", "Tid"],
        "Koreanska": ["Språk", "Koreanska", "Läs hangul", "K-pop-ord"],
        RAKNA: ["Matte"],
    },
}

_LOOKUP = {sub: {t: area for area, topics in areas.items() for t in topics} for sub, areas in AREAS.items()}


def area_of(subject: str, topic: str) -> str:
    return _LOOKUP.get(subject, {}).get(topic) or GLOBAL.get(topic) or OVRIGT


def order(subject: str) -> list:
    """Områdesnamn i den ordning de visas: ämnets egna, sedan bilder, räkneuppgifter och övrigt."""
    own = [a for a in AREAS.get(subject, {}) if a != RAKNA]
    return own + [BILDER, RAKNA, OVRIGT]
