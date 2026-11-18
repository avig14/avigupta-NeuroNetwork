"""Canary matcher (hardened after red-team round 1, docs/redteam_log.md).

Round 1 showed a raw substring match missed 9 of 11 cheap evasions (case, spacing, punctuation,
homoglyphs, zero-width chars, reversal, ROT13, hex, base64, split across messages).
This matcher normalises first, then also tries the common reversible transforms.

HONEST LIMIT: no scanner can catch an arbitrary cipher or a paraphrase of the secret. This closes
the cheap, well-known evasions only. Unknown encodings remain a residual risk (see the red-team log).
"""
from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata

# A few common Cyrillic / Greek look-alikes (after casefold) -> Latin.
_HOMO = {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s",
         "ј": "j", "ԁ": "d", "ο": "o", "α": "a", "ν": "v", "ι": "i", "ρ": "p"}
_HOMO_TABLE = str.maketrans(_HOMO)
_HEX = re.compile(r"(?:[0-9a-fA-F]{2}){6,}")
_B64 = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")


def norm(s: str) -> str:
    """NFKC, drop invisible format chars, casefold, fold look-alikes, keep only [a-z0-9]."""
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    s = s.casefold().translate(_HOMO_TABLE)
    return re.sub(r"[^a-z0-9]", "", s)


def _decoded_views(text: str) -> list[tuple[str, str]]:
    """(method, decoded text) for hex / base64 runs found in the text."""
    views: list[tuple[str, str]] = []
    for m in _HEX.finditer(text):
        try:
            views.append(("hex", bytes.fromhex(m.group(0)).decode("utf-8", "ignore")))
        except ValueError:
            pass
    for m in _B64.finditer(text):
        raw = m.group(0).rstrip("=")
        raw += "=" * (-len(raw) % 4)
        for dec in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                views.append(("base64", dec(raw).decode("utf-8", "ignore")))
                break
            except (binascii.Error, ValueError):
                continue
    return views


def find_canary(text: str, tokens: list[str]) -> tuple[str, str] | None:
    """Return (token, method) if a canary appears in `text` in any covered form, else None."""
    if not text:
        return None
    for tok in tokens:
        if tok in text:
            return tok, "exact"
        nt = norm(tok)
        if not nt:
            continue
        nx = norm(text)
        if nt in nx:
            return tok, "normalised (case/spacing/punctuation/homoglyph/zero-width)"
        if nt[::-1] in nx:
            return tok, "reversed"
        if codecs.encode(nt, "rot13") in nx:
            return tok, "rot13"
        for method, dec in _decoded_views(text):
            if nt in norm(dec) or nt[::-1] in norm(dec):
                return tok, method
    return None
