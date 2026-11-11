"""Pull the trouble code and vehicle details out of a typed or spoken sentence."""
import re
from typing import Iterable, Optional

CODE_RE = re.compile(r"^[PBCU][0-3][0-9A-F]{3}$")

_UNITS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_TEENS = {
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
# Speech-to-text sometimes hears the code letter as a word. "you" and "see" are left out
# on purpose: "thank you, 2015 Honda" must not turn into the code U2015.
_LETTERS = {"pee": "p", "pea": "p", "bee": "b"}

_MAKES = {
    "acura": "Acura", "alfa romeo": "Alfa Romeo", "audi": "Audi", "bmw": "BMW",
    "buick": "Buick", "cadillac": "Cadillac", "chevrolet": "Chevrolet", "chevy": "Chevrolet",
    "chrysler": "Chrysler", "dodge": "Dodge", "fiat": "Fiat", "ford": "Ford",
    "genesis": "Genesis", "gmc": "GMC", "honda": "Honda", "hyundai": "Hyundai",
    "infiniti": "Infiniti", "jaguar": "Jaguar", "jeep": "Jeep", "kia": "Kia",
    "land rover": "Land Rover", "lexus": "Lexus", "lincoln": "Lincoln", "mazda": "Mazda",
    "mercedes-benz": "Mercedes-Benz", "mercedes benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "mini": "Mini", "mitsubishi": "Mitsubishi",
    "nissan": "Nissan", "pontiac": "Pontiac", "porsche": "Porsche", "ram": "Ram",
    "saturn": "Saturn", "scion": "Scion", "subaru": "Subaru", "suzuki": "Suzuki",
    "tesla": "Tesla", "toyota": "Toyota", "volkswagen": "Volkswagen", "vw": "Volkswagen",
    "volvo": "Volvo",
}
_MAKE_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _MAKES), key=len, reverse=True)) + r")\b", re.I
)
# First words of two-word model names ("Grand Cherokee", "Model 3", "Santa Fe").
_MODEL_PREFIXES = {"grand", "model", "santa", "town", "range", "land", "super", "monte"}
_STOP = {
    "with", "and", "at", "has", "have", "is", "it", "its", "that", "the", "a", "on", "in",
    "code", "says", "shows", "showing", "throwing", "what", "does", "mean", "means", "my",
    "i", "got", "about", "around", "for", "of", "or", "which", "check", "engine", "light",
}
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
_MILEAGE_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|thousand)?\s*(?:miles?\b|mi\b)", re.I
)
_MILEAGE_K_RE = re.compile(r"\b(\d{2,3})\s*k\b", re.I)


def _spoken_to_digits(text: str) -> str:
    """'p zero four twenty' -> 'p 0 4 20'."""
    words = re.findall(r"[a-z]+|\d+|[^a-z\d\s]", text.lower())
    out: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if word in _TENS:
            if nxt in _UNITS and nxt not in ("zero", "oh", "o"):
                out.append(str(_TENS[word] + int(_UNITS[nxt])))
                i += 2
                continue
            out.append(str(_TENS[word]))
        elif word == "hundred":
            out.append("00")
        else:
            out.append(_UNITS.get(word) or _TEENS.get(word) or _LETTERS.get(word) or word)
        i += 1
    return " ".join(out)


def find_codes(text: str) -> list[str]:
    """Every trouble code mentioned in the text, in the order heard."""
    found: list[str] = []

    def add(code: str) -> None:
        code = code.upper()
        if CODE_RE.match(code) and code not in found:
            found.append(code)

    # Written normally, or with a dash or space after the letter: P0420, P-0420, P 0420.
    for m in re.finditer(r"\b([PBCU])[\s\-]?([0-3][0-9A-F]{3})\b", text, re.I):
        add(m.group(1) + m.group(2))
    # Spelled out or split up by speech-to-text: "P 0 4 20", "p zero four two zero".
    spoken = _spoken_to_digits(text)
    for m in re.finditer(r"\b([pbcu])((?:[\s\-.,]*\d){2,4})(?!\s*\d)", spoken):
        digits = re.sub(r"\D", "", m.group(2))
        if len(digits) == 4:
            add(m.group(1) + digits)
    return found


def is_code(text: str) -> bool:
    return bool(CODE_RE.match(text.upper()))


def pick_code(text: str, known: Iterable[str] = ()) -> Optional[str]:
    """The most likely code in the text, preferring one the database knows."""
    codes = find_codes(text)
    known = set(known)
    for code in codes:
        if code in known:
            return code
    return codes[0] if codes else None


def _mileage(text: str) -> Optional[int]:
    m = _MILEAGE_RE.search(text)
    if m:
        value = float(m.group(1).replace(",", ""))
        if m.group(2):
            value *= 1000
        return int(value)
    m = _MILEAGE_K_RE.search(text)
    return int(m.group(1)) * 1000 if m else None


def _model_after(text: str) -> Optional[str]:
    """The model name that follows the make: 'Accord', 'F-150', 'Grand Cherokee'."""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", text)
    picked: list[str] = []
    for token in tokens[:2]:
        if token.lower() in _STOP or find_codes(token) or _YEAR_RE.fullmatch(token):
            break
        picked.append(token)
        if token.lower() not in _MODEL_PREFIXES:
            break
    if not picked:
        return None
    # "f-150" -> "F-150", "rav4" -> "RAV4", "accord" -> "Accord"
    return " ".join(t.upper() if "-" in t or any(c.isdigit() for c in t)
                    else t if any(c.isupper() for c in t) else t.capitalize()
                    for t in picked)


def parse_question(text: str, known: Iterable[str] = ()) -> dict:
    """Extract code, year, make, model and mileage. Missing pieces are None."""
    result = {"code": pick_code(text, known), "year": None, "make": None,
              "model": None, "mileage": None}

    result["mileage"] = _mileage(text)

    year = _YEAR_RE.search(text)
    if year:
        result["year"] = int(year.group(1))

    make = _MAKE_RE.search(text)
    if make:
        result["make"] = _MAKES[make.group(1).lower()]
        result["model"] = _model_after(text[make.end():])
    return result


_PREFIX = {
    "P": "powertrain (engine and transmission)",
    "B": "body (airbags, seats, climate, lighting)",
    "C": "chassis (brakes, steering, suspension)",
    "U": "network (communication between the car's computers)",
}
_P_SUBSYSTEM = {
    "0": "fuel and air metering, or emission controls",
    "1": "fuel and air metering",
    "2": "fuel and air metering (injector circuit)",
    "3": "ignition system or misfire",
    "4": "auxiliary emission controls",
    "5": "vehicle speed, idle control, or auxiliary inputs",
    "6": "computer and output circuits",
    "7": "transmission",
    "8": "transmission",
    "9": "transmission",
    "A": "hybrid propulsion",
}


def describe_code_structure(code: str) -> str:
    """What the letters and digits of a code tell you, for codes not in the database."""
    code = code.upper()
    area = _PREFIX[code[0]]
    kind = "generic (same meaning on every make)" if code[1] in "02" else "manufacturer-specific"
    if code[1] == "3":
        kind = "generic or manufacturer-specific, depending on the number"
    text = f"{code} is a {kind} {area} code"
    if code[0] == "P" and code[2] in _P_SUBSYSTEM:
        text += f" in the {_P_SUBSYSTEM[code[2]]} group"
    return text + "."
