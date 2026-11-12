"""Vilken version som körs. RELEASE är en etikett (datum, med .2, .3 … om det blir flera samma dag) som räknas upp
vid varje ändring, så att man ser vilken som är nyast. Signaturen är en kort kontrollsumma över alla filer i app/ och
visar på riktigt om två miljöer kör exakt samma kod, även om etiketten glömts bort."""
import hashlib
from functools import lru_cache
from pathlib import Path

RELEASE = "2026.11.12.2"
SUFFIXES = {".py", ".html", ".css", ".js", ".json"}


def code_signature(root: Path | None = None) -> str:
    root = Path(root or Path(__file__).parent)
    h = hashlib.sha1()
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix in SUFFIXES and "__pycache__" not in f.parts:
            h.update(f.relative_to(root).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:7]


@lru_cache(maxsize=1)
def info() -> dict:
    sig = code_signature()
    return {"release": RELEASE, "signature": sig, "label": f"{RELEASE} ({sig})"}
