"""Bounded verbatim excerpts of observed text, never summaries or inferred facts.

The original body belongs in communication_archive. These excerpts deliberately
omit spans and cannot establish that the browser exposed the complete message.
"""
from __future__ import annotations

import re


OMISSION = " …[생략]… "
_OMISSION_RE = re.compile(r"\s*…\[(?:중간 )?생략\]…\s*")
PATH_ONLY_KW = {"temp", "downloads", "다운로드", "임시"}


def make_text_filter(exclude_keywords):
    """Share the existing signal privacy policy with full-body collectors."""
    keywords = [str(word).lower() for word in (exclude_keywords or ()) if word]
    non_ascii = [word for word in keywords if not word.isascii() and word not in PATH_ONLY_KW]
    ascii_words = [word for word in keywords if word.isascii() and word not in PATH_ONLY_KW]
    pattern = (re.compile("|".join(f"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"
                                 for word in ascii_words)) if ascii_words else None)

    def hit(low):
        found = next((word for word in non_ascii if word in low), None)
        if not found and pattern:
            match = pattern.search(low)
            found = match.group(0) if match else None
        return found
    return hit


def body_is_filtered(text, exclude_keywords):
    """Check the entire observed body before any excerpt or archive is made."""
    return bool(make_text_filter(exclude_keywords)(str(text or "").lower()))


def make_excerpt(text, limit=4000):
    """Return at most limit characters from the beginning, middle and end.

    Whitespace is normalized only in the excerpt. Re-excerpting our own three
    spans retains a sample from each span instead of sampling omission markers.
    Tiny limits cannot hold three spans; they retain a marked prefix instead.
    """
    text = " ".join(str(text or "").split())
    limit = max(0, int(limit))
    if len(text) <= limit:
        return text
    if limit <= len(OMISSION) * 2 + 3:
        return text[:max(0, limit - 1)] + ("…" if limit else "")
    parts = [part.strip() for part in _OMISSION_RE.split(text) if part.strip()]
    available = limit - 2 * len(OMISSION)
    head_n = (available + 2) // 3
    middle_n = (available + 1) // 3
    tail_n = available - head_n - middle_n
    if len(parts) >= 3:
        head, middle, tail = parts[0], parts[len(parts) // 2], parts[-1]
    else:
        head = middle = tail = text
    middle_start = max(0, len(middle) // 2 - middle_n // 2)
    spans = (head[:head_n], middle[middle_start:middle_start + middle_n], tail[-tail_n:])
    return OMISSION.join(spans)
