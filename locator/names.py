"""Place-name normalisation, matching and display formatting.

Official datasets spell names inconsistently: ``TAMIL NĀDU`` in the Survey of
India layer, ``Tamil Nadu`` in LGD, ``Thirumangalam`` in one register and
``Tirumangalam`` in another. Everything in this project compares names through
:func:`key`, which reduces a name to a stable comparison key, and displays them
through :func:`display`, which produces the brand's capitalisation.

Nothing here guesses at geometry or invents a name. It only decides whether two
spellings refer to the same unit, and that decision is always reported to the
user when it comes from the alias table rather than an exact match.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "strip_diacritics",
    "key",
    "display",
    "AliasTable",
    "load_aliases",
]


# Words that stay lowercase inside a place name when they are not the first
# word. Deliberately short: Indian place names capitalise almost everything.
_LOWERCASE_PARTICLES = {"and", "of", "the", "de", "da"}

# Expanded before keying so "Dadra & Nagar Haveli" matches "Dadra and Nagar
# Haveli".
_AMPERSAND = re.compile(r"\s*&\s*")

# Anything that is not a letter, digit or single space is noise for matching:
# "T. Kallupatti" and "T Kallupatti" are the same block.
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_MULTISPACE = re.compile(r"\s+")


def strip_diacritics(text: str) -> str:
    """Return ``text`` with combining marks removed.

    ``ARUNĀCHAL PRADESH`` becomes ``ARUNACHAL PRADESH``. Survey of India layers
    carry macrons and other marks that no other register uses.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def key(name: str) -> str:
    """Reduce a place name to its comparison key.

    The key is lowercase, unaccented, punctuation-free and single-spaced, with
    ``&`` expanded to ``and``. It is used for every name comparison in this
    project; it is never shown to the user.

    >>> key("TAMIL NĀDU")
    'tamil nadu'
    >>> key("T. Kallupatti")
    't kallupatti'
    >>> key("Dadra & Nagar Haveli")
    'dadra and nagar haveli'
    """
    if name is None:
        return ""
    text = strip_diacritics(str(name)).lower()
    text = _AMPERSAND.sub(" and ", text)
    text = _NON_ALNUM.sub(" ", text)
    return _MULTISPACE.sub(" ", text).strip()


def display(name: str) -> str:
    """Return ``name`` capitalised the way it should appear on a map.

    Place names are proper nouns, so each significant word is capitalised:
    ``MADURAI EAST`` becomes ``Madurai East``. Initials keep their full stop
    (``T. Kallupatti``) and hyphenated parts are capitalised either side.

    The brand's sentence-case rule governs panel titles and legends, which are
    sentences; it does not lowercase proper nouns.
    """
    if name is None:
        return ""
    text = _MULTISPACE.sub(" ", strip_diacritics(str(name)).strip())
    if not text:
        return ""

    words = []
    for index, word in enumerate(text.split(" ")):
        words.append(_capitalise_word(word, first=index == 0))
    return " ".join(words)


def _capitalise_word(word: str, *, first: bool) -> str:
    """Capitalise a single word of a place name, respecting inner punctuation."""
    if not word:
        return word

    lowered = word.lower()
    if not first and lowered.strip(".") in _LOWERCASE_PARTICLES:
        return lowered
    if word == "&":
        return "&"

    # Capitalise either side of a hyphen, slash or bracket, and after a full
    # stop, so that "t.kallupatti" reads "T.Kallupatti" and "kaimur (bhabua)"
    # reads "Kaimur (Bhabua)".
    parts = re.split(r"([-/.()])", lowered)
    return "".join(
        part if part in "-/.()" else (part[:1].upper() + part[1:]) for part in parts
    )


@dataclass(frozen=True)
class AliasHit:
    """A name that matched only after going through the alias table."""

    level: str
    given: str
    canonical: str
    note: str

    def message(self) -> str:
        return (
            f"Read {self.level} {self.given!r} as {self.canonical!r}"
            + (f" ({self.note})" if self.note else "")
        )


class AliasTable:
    """Accepted spelling variants, loaded from ``data/aliases.csv``.

    The table maps an alternative spelling to the canonical name used by the
    authoritative register (LGD). Lookups are keyed through :func:`key`, so the
    table only needs entries for genuine differences in spelling, not for
    differences in case, accents or punctuation.
    """

    def __init__(self, rows: list[dict[str, str]] | None = None) -> None:
        self._by_level: dict[str, dict[str, tuple[str, str]]] = {}
        for row in rows or []:
            level = (row.get("level") or "").strip().lower()
            alias = (row.get("alias") or "").strip()
            canonical = (row.get("canonical") or "").strip()
            if not level or not alias or not canonical:
                continue
            note = (row.get("note") or "").strip()
            self._by_level.setdefault(level, {})[key(alias)] = (canonical, note)

    def resolve(self, level: str, name: str) -> tuple[str, AliasHit | None]:
        """Return the canonical spelling of ``name`` and how it was reached.

        If the name is not in the table it is returned unchanged with ``None``;
        an unknown name is not an error here, it is simply not an alias.
        """
        entry = self._by_level.get(level.lower(), {}).get(key(name))
        if entry is None:
            return name, None
        canonical, note = entry
        return canonical, AliasHit(level=level, given=name, canonical=canonical, note=note)

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_level.values())


def load_aliases(path: str | Path) -> AliasTable:
    """Load the alias table, returning an empty table if the file is absent."""
    path = Path(path)
    if not path.exists():
        return AliasTable()
    with path.open(newline="", encoding="utf-8") as handle:
        return AliasTable(list(csv.DictReader(handle)))
