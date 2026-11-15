"""Text normalization — shared by EPUB and PDF pipelines. Fast path only."""
from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ß": "ss", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "\u00ad": "",  # soft hyphen
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
}
_LIG_RE = re.compile("|".join(re.escape(k) for k in _LIGATURES))
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DEHYPHEN_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")


def expand_ligatures(text: str) -> str:
    return _LIG_RE.sub(lambda m: _LIGATURES[m.group(0)], text)


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = expand_ligatures(text)
    text = _CONTROL_RE.sub("", text)
    return text


def dehyphenate(text: str) -> str:
    """exam-\\nple -> example ; also handles 'exam- ple' (space-joined)."""
    text = _DEHYPHEN_RE.sub(r"\1\2", text)
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)
    return text


def collapse_blank_lines(text: str, max_blank: int = 1) -> str:
    # max_blank=1 means at most one empty line (i.e. \n\n max, no \n\n\n)
    text = _TRAILING_WS_RE.sub("\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n" if text.strip() else ""


def clean_block(text: str) -> str:
    """Clean a single paragraph/block: join wrapped lines, normalize spaces."""
    text = normalize_unicode(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    joined = lines[0]
    for ln in lines[1:]:
        if joined.endswith("-") and ln and ln[0].islower():
            # Soft hyphenation: exam- + ple -> example
            joined = joined[:-1] + ln
        else:
            joined = joined + " " + ln
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined


def normalize_document(text: str) -> str:
    text = normalize_unicode(text)
    text = dehyphenate(text)
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    # Ensure single trailing newline, no leading blank lines
    text = text.strip("\n")
    return text + "\n" if text else ""
