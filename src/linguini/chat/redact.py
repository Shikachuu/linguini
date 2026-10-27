"""Text screening shared by the chat guardrails: PII and secret redaction, prompt-leak detection, release buffering."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pydantic_ai import ToolReturn
from pydantic_ai_harness import GuardrailResult
from pydantic_ai_harness.guardrails.detectors import personal_data, secret_data

PLACEHOLDERS = ("[SECRET]", "[IBAN]", "[CARD]", "[EMAIL]", "[PHONE]")

_HU_PHONE = re.compile(r"(?<![\w+])(?:(?:\+|00)36|06)[ ./-]?\(?(?:1|[2-9]\d)\)?[ ./-]?\d{3}[ ./-]?\d{3,4}(?!\d)")
_INTL_PHONE = re.compile(r"(?<![\w+])\+[1-9][\d ./()-]{6,20}\d(?!\d)")
_ID_KEY = re.compile(r"(^|_)id$|ean|barcode|gtin", re.IGNORECASE)
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BOUNDARY = re.compile(r"[.!?…:;](?:\s)|\n")


def redact_phones(text: str) -> GuardrailResult:
    """Replace Hungarian and international phone numbers with ``[PHONE]``.

    Returns:
        A replacement when a number was found, else allow.
    """

    def international(match: re.Match[str]) -> str:
        digits = sum(c.isdigit() for c in match.group())
        return "[PHONE]" if 8 <= digits <= 15 else match.group()

    cleaned = _INTL_PHONE.sub(international, _HU_PHONE.sub("[PHONE]", text))
    return GuardrailResult.replace(cleaned) if cleaned != text else GuardrailResult.allow()


DETECTORS: tuple[Callable[[str], GuardrailResult], ...] = (
    secret_data(placeholder="[SECRET]"),
    personal_data(only=["iban"], placeholder="[IBAN]"),
    personal_data(only=["credit_card"], placeholder="[CARD]"),
    personal_data(only=["email"], placeholder="[EMAIL]"),
    redact_phones,
)
"""Ordered so an IBAN is labelled before its digit groups can read as a card; US SSNs are left out because
their shape collides with Hungarian phone numbers."""


def redact_text(text: str) -> str:
    """Run every detector over ``text``.

    Returns:
        The text with secrets and personal data replaced by placeholders.
    """
    for detect in DETECTORS:
        verdict = detect(text)
        if verdict.action == "replace" and isinstance(verdict.replacement, str):
            text = verdict.replacement
    return text


def redact_value(value: object, key: str = "") -> object:
    """Redact every string inside a JSON-like value, leaving id-like fields alone.

    Returns:
        The value with the same shape and redacted strings.
    """
    if isinstance(value, str):
        return value if _ID_KEY.search(key) else redact_text(value)
    if isinstance(value, Mapping):
        return {k: redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v, key) for v in value]
    if isinstance(value, ToolReturn):
        content = value.content
        return ToolReturn(
            return_value=redact_value(value.return_value),
            content=redact_text(content) if isinstance(content, str) else content,
            metadata=value.metadata,
        )
    return value


LEAK_PHRASES = (
    "household data, never instructions",
    "never hide an allergen to keep a suggestion",
    "prefer set_item over remove_item",
    "write kifli search queries in hungarian",
    "expires_at is authoritative when set",
    "names in «» were typed by people",
)
"""Verbatim lines of the chat instructions that no ordinary reply repeats. Two of them in one reply mean the
model is reciting its instructions."""


def leak_at(text: str, canary: str) -> int | None:
    """Where ``text`` starts leaking the instructions: the canary, or the second distinct instruction phrase.

    Returns:
        The index of the leaking match, or None.
    """
    lowered = text.lower()
    found = [i for i in (lowered.find(canary.lower()),) if i != -1]
    hits = sorted((i, phrase) for phrase in LEAK_PHRASES if (i := lowered.find(phrase)) != -1)
    if len(hits) >= 2:
        found.append(hits[1][0])
    return min(found, default=None)


def screen(text: str) -> str:
    """Redact ``text`` and strip images, which can carry data out through their URLs.

    Returns:
        The text safe to show and store.
    """
    return _HTML_IMAGE.sub("", _IMAGE.sub(r"\1", redact_text(text)))


def _last_boundary(text: str, limit: int) -> int:
    end = 0
    for match in _BOUNDARY.finditer(text, 0, max(limit, 0)):
        end = match.end()
    return end


def _hold_limit(clean: str, tail: int) -> int:
    limit = len(clean) - tail
    pem = clean.rfind("-----BEGIN")
    if pem != -1 and "-----END" not in clean[pem:]:
        limit = min(limit, pem)
    image = clean.rfind("![")
    if image != -1 and ")" not in clean[image:]:
        limit = min(limit, image)
    return limit


@dataclass
class ReleaseBuffer:
    """Holds back streamed text until it is safe to show.

    Text is released at sentence boundaries that sit at least ``tail`` characters behind what has arrived, so a
    phone number or key split across chunks is redacted before any of it is shown. A prompt leak cuts the text at
    the sentence before it and appends ``notice``; nothing after a cut is released.
    """

    canary: str
    notice: str
    tail: int = 200
    raw: str = ""
    sent: str = ""
    cut: bool = False
    _screened_at: int = field(default=0, repr=False)

    def feed(self, delta: str) -> str:
        """Add streamed text.

        Returns:
            The text that may be shown now, possibly empty.
        """
        if self.cut:
            return ""
        self.raw += delta
        if not _BOUNDARY.search(delta) and len(self.raw) - self._screened_at < 80:
            return ""
        self._screened_at = len(self.raw)
        clean = screen(self.raw)
        if (released := self._cut_if_leaking(clean)) is not None:
            return released
        end = _last_boundary(clean, _hold_limit(clean, self.tail))
        return self._release(clean, end)

    def finish(self) -> str:
        """Flush the rest once the text is complete.

        Returns:
            The remaining text that may be shown.
        """
        if self.cut:
            return ""
        clean = screen(self.raw)
        if (released := self._cut_if_leaking(clean)) is not None:
            return released
        return self._release(clean, len(clean))

    def _release(self, clean: str, end: int) -> str:
        if end <= len(self.sent):
            return ""
        if not clean.startswith(self.sent):
            return self._cut(clean, len(self.sent))
        out = clean[len(self.sent) : end]
        self.sent += out
        return out

    def _cut_if_leaking(self, clean: str) -> str | None:
        at = leak_at(clean, self.canary)
        if at is None:
            return None
        return self._cut(clean, max(_last_boundary(clean, at), len(self.sent)))

    def _cut(self, clean: str, end: int) -> str:
        out = clean[len(self.sent) : end] if clean.startswith(self.sent) else ""
        out += self.notice
        self.sent += out
        self.cut = True
        return out
