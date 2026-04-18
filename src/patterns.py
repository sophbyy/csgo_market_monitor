"""Russian name pattern detection for Steam bot account identification.

Bot accounts on CS:GO trading platforms typically use vanity URLs and nicknames
with concatenated Russian first + last names, optionally followed by digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ~80 common Russian first names, transliterated to Latin script.
RUSSIAN_FIRST_NAMES: frozenset[str] = frozenset(
    {
        "adam",
        "adel",
        "agata",
        "akim",
        "aleksei",
        "aleksey",
        "alexander",
        "alexei",
        "alexey",
        "alina",
        "alla",
        "anastasia",
        "andrei",
        "andrey",
        "anna",
        "anton",
        "artem",
        "berta",
        "bogdan",
        "boris",
        "daniil",
        "daria",
        "denis",
        "diana",
        "dmitri",
        "dmitriy",
        "dmitry",
        "egor",
        "ekaterina",
        "elena",
        "elina",
        "elvira",
        "eva",
        "evgeni",
        "evgeniy",
        "fedor",
        "filipp",
        "foma",
        "galina",
        "gennadi",
        "georgi",
        "gleb",
        "hakim",
        "igor",
        "ilya",
        "inna",
        "irina",
        "ivan",
        "kirill",
        "klara",
        "konstantin",
        "larisa",
        "lev",
        "lidia",
        "ludmila",
        "magda",
        "maksim",
        "mara",
        "maria",
        "marina",
        "mark",
        "matvei",
        "mikhail",
        "nadezhda",
        "natalia",
        "natalya",
        "nikita",
        "nikolai",
        "nina",
        "oleg",
        "olga",
        "pavel",
        "polina",
        "roman",
        "ruslan",
        "sergei",
        "sergey",
        "sofia",
        "stanislav",
        "svetlana",
        "tatiana",
        "timofei",
        "timur",
        "vadim",
        "valentin",
        "valentina",
        "valeria",
        "vasili",
        "vera",
        "viktor",
        "vladislav",
        "vladimir",
        "yaroslav",
        "yuri",
        "zhanna",
        "bekum",
    },
)

# ~80 common Russian last names, transliterated to Latin script.
RUSSIAN_LAST_NAMES: frozenset[str] = frozenset(
    {
        "aleksandrov",
        "alekseev",
        "andreev",
        "antonov",
        "baranov",
        "belov",
        "bobrov",
        "bogdanov",
        "bondarenko",
        "borisov",
        "burov",
        "bykov",
        "chistyakov",
        "davydov",
        "dmitriev",
        "egorov",
        "fedorov",
        "filatov",
        "fomin",
        "frolov",
        "gavrilov",
        "gerasimov",
        "gorbunov",
        "grigoryev",
        "gromov",
        "gusev",
        "ignatov",
        "ivanov",
        "kalinin",
        "kazakov",
        "kiselyov",
        "klimov",
        "komarov",
        "konovalov",
        "kozlov",
        "krasilnikov",
        "krukov",
        "kuznetsov",
        "lebedev",
        "litvinov",
        "loginov",
        "makarov",
        "medvedev",
        "melnikov",
        "mikhailov",
        "morozov",
        "mugilysaqo",
        "nikitin",
        "nikolaev",
        "novikov",
        "orlov",
        "osipov",
        "pavlov",
        "petrov",
        "polyakov",
        "popov",
        "romanov",
        "rusakov",
        "ryabov",
        "savin",
        "semenov",
        "sidorov",
        "smirnov",
        "sokolov",
        "solovyov",
        "stepanov",
        "surkov",
        "tarasov",
        "titov",
        "vasiliev",
        "vinogradov",
        "volkov",
        "vorobyov",
        "voronov",
        "yakovlev",
        "zakharov",
        "zaytsev",
        "zhukov",
        "zukov",
    },
)


# Precomputed sorted names longest-first for greedy matching.
_FIRST_SORTED = sorted(RUSSIAN_FIRST_NAMES, key=len, reverse=True)
_LAST_SORTED = sorted(RUSSIAN_LAST_NAMES, key=len, reverse=True)

_TRAILING_DIGITS_RE = re.compile(r"^([a-z]+?)(\d+)$")
_ALPHA_ONLY_RE = re.compile(r"^[a-z]+$")


@dataclass(frozen=True)
class NamePatternResult:
    """Result of bot-name pattern detection."""

    matches: bool
    pattern_type: str  # "russian_name", "russian_name_digits", "unknown"
    confidence: float  # 0.0 – 1.0


def _try_split_name(name: str) -> tuple[str | None, str | None]:
    """Try to split *name* into a known firstname + known lastname.

    Uses greedy longest-first matching on the first name, then checks
    whether the remainder is a known last name.
    """
    for first in _FIRST_SORTED:
        if name.startswith(first):
            remainder = name[len(first) :]
            if remainder and remainder in RUSSIAN_LAST_NAMES:
                return first, remainder
    return None, None


def _partial_match(name: str) -> str | None:
    """Return which part matched if only one of firstname/lastname is found."""
    for first in _FIRST_SORTED:
        if name.startswith(first) and len(name) > len(first):
            return "first_only"
    for last in _LAST_SORTED:
        if name.endswith(last) and len(name) > len(last):
            return "last_only"
    return None


def detect_name_pattern(vanity_or_nickname: str) -> NamePatternResult:
    """Detect whether *vanity_or_nickname* matches a bot-like naming pattern.

    Parameters
    ----------
    vanity_or_nickname:
        A Steam vanity URL slug or nickname (e.g. ``"fomakrukov242"``).

    Returns
    -------
    NamePatternResult
        Whether the string matches, which pattern type, and confidence.
    """
    raw = vanity_or_nickname.strip().lower()

    # Strip trailing digits to get the "word" part.
    has_digits = False
    m = _TRAILING_DIGITS_RE.match(raw)
    if m:
        word = m.group(1)
        has_digits = True
    else:
        word = raw

    # Must be pure alpha after digit stripping.
    if not _ALPHA_ONLY_RE.match(word):
        return NamePatternResult(matches=False, pattern_type="unknown", confidence=0.0)

    # --- Full match: firstname + lastname ---
    first, last = _try_split_name(word)
    if first and last:
        ptype = "russian_name_digits" if has_digits else "russian_name"
        # Confidence: full match is high; slightly higher when digits present
        # (bots very commonly append digits).
        confidence = 0.95 if has_digits else 0.90
        return NamePatternResult(matches=True, pattern_type=ptype, confidence=confidence)

    # --- Partial match: only first or last name found ---
    partial = _partial_match(word)
    if partial:
        ptype = "russian_name_digits" if has_digits else "russian_name"
        confidence = 0.6 if has_digits else 0.5
        return NamePatternResult(matches=True, pattern_type=ptype, confidence=confidence)

    # --- Heuristic: looks like two concatenated words (10-25 lowercase alpha) ---
    if 10 <= len(word) <= 25:
        ptype = "russian_name_digits" if has_digits else "unknown"
        return NamePatternResult(matches=True, pattern_type=ptype, confidence=0.3)

    return NamePatternResult(matches=False, pattern_type="unknown", confidence=0.0)
