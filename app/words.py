"""Ordlistan: ord med ordklass och böjningsformer som de svenska generatorerna använder."""
import json

POS = ["substantiv", "verb", "adjektiv", "adverb", "preposition", "pronomen", "räkneord",
       "konjunktion", "subjunktion", "interjektion", "glosa", "koreanska"]
FORM_KEYS = {"plural", "bestamd", "bestamd_plural", "presens", "preteritum", "supinum", "imperativ",
             "komparativ", "superlativ", "neutrum", "past", "pastpart"}


class WordBank:
    def __init__(self, words):
        self.words = list(words)

    @classmethod
    def from_db(cls, db):
        words = []
        for r in db.execute("SELECT word, pos, level, data FROM words WHERE active=1"):
            d = json.loads(r["data"])
            d.update(word=r["word"], pos=r["pos"], level=r["level"])
            words.append(d)
        return cls(words)

    @staticmethod
    def _has(w, key) -> bool:
        return bool(w.get("forms", {}).get(key) or w.get(key))

    def has(self, pos, level) -> bool:
        return any(w["pos"] == pos and w["level"] <= level and not w.get("ambig") for w in self.words)

    def pick(self, rng, pos, level, need=(), quiz=False, exclude=()):
        from .generators import NoData
        pos = [pos] if isinstance(pos, str) else list(pos)
        cands = [w for w in self.words
                 if w["pos"] in pos and w["level"] <= level and w["word"] not in exclude
                 and all(self._has(w, k) for k in need) and not (quiz and w.get("ambig"))]
        if not cands:
            raise NoData(f"inga ord: {pos} nivå {level}")
        exact = [w for w in cands if w["level"] == level]
        pool = exact if exact and rng.random() < 0.65 else cands
        return rng.choice(pool)

    def distractors(self, rng, k, pos_in, level, forbid_pos=None, exclude=()):
        """k olika ord (utan dubbletter) från ordklasserna pos_in som inte kan vara rätt svar."""
        from .generators import NoData
        forbidden = set(exclude)
        if forbid_pos:
            forbidden |= {w["word"] for w in self.words if w["pos"] == forbid_pos}
        seen, cands = set(), []
        for w in self.words:
            if w["pos"] in pos_in and w["level"] <= level and not w.get("ambig") and w["word"] not in forbidden \
                    and w["word"] not in seen:
                seen.add(w["word"])
                cands.append(w)
        if len(cands) < k:
            raise NoData("för få avledare")
        return rng.sample(cands, k)


def validate_word(d):
    """Returnerar (rad, fel)."""
    if not isinstance(d, dict):
        return None, "inte ett objekt"
    word = str(d.get("word", "")).strip()
    pos = str(d.get("pos", "")).strip().lower()
    if not word or len(word) > 40:
        return None, "word saknas eller är för långt"
    if pos not in POS:
        return None, f"pos måste vara en av: {', '.join(POS)}"
    try:
        level = int(d.get("level", 1))
    except (TypeError, ValueError):
        return None, "level måste vara 1–5"
    if not 1 <= level <= 5:
        return None, "level måste vara 1–5"
    data = {}
    forms = d.get("forms", {})
    if not isinstance(forms, dict):
        return None, "forms måste vara ett objekt"
    clean = {}
    for k, v in forms.items():
        if k not in FORM_KEYS:
            return None, f"okänd form '{k}'"
        if not isinstance(v, str) or not v.strip() or len(v) > 40:
            return None, f"formen '{k}' är ogiltig"
        clean[k] = v.strip()
    if clean:
        data["forms"] = clean
    if pos == "substantiv" and d.get("gender") is not None:
        if d["gender"] not in ("en", "ett"):
            return None, "gender måste vara 'en' eller 'ett'"
        data["gender"] = d["gender"]
    for k in ("antonym", "synonym", "example"):
        if d.get(k):
            data[k] = str(d[k]).strip()[:120]
    if pos in ("glosa", "koreanska"):
        sv = d.get("sv")
        sv = [sv] if isinstance(sv, str) else sv
        if not isinstance(sv, list) or not sv or not all(isinstance(x, str) and x.strip() and len(x) <= 40 for x in sv):
            return None, "glosor måste ha 'sv' (svensk översättning, en text eller en lista)"
        data["sv"] = [x.strip() for x in sv]
        if d.get("hangul"):
            if not isinstance(d["hangul"], str) or len(d["hangul"]) > 20:
                return None, "hangul är ogiltigt"
            data["hangul"] = d["hangul"].strip()
    if d.get("ambig"):
        data["ambig"] = True
    return {"word": word, "pos": pos, "level": level, "data": json.dumps(data, ensure_ascii=False)}, None


def import_words(db, items) -> dict:
    if not isinstance(items, list):
        raise ValueError("words måste vara en lista")
    added = skipped = 0
    errors = []
    for i, item in enumerate(items, start=1):
        row, err = validate_word(item)
        if err:
            errors.append(f"Ord {i}: {err}")
            continue
        cur = db.execute("INSERT OR IGNORE INTO words(word, pos, level, data) VALUES (:word,:pos,:level,:data)", row)
        if cur.rowcount:
            added += 1
        else:
            skipped += 1
    db.commit()
    return {"added": added, "skipped": skipped, "errors": errors}
