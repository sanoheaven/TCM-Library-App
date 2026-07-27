"""Reusable, non-destructive OCR risk detection for TCM source review.

The detector only raises review flags. It never replaces OCR text or asserts a
medical interpretation. Glossary matches are cues for human comparison with
the source image, not automatic corrections.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re


LOW_CONFIDENCE = 0.99
MAX_TERM_EDIT_DISTANCE = 1

# Compact seed, intended to grow only from independently confirmed terms.
# Do not insert the expected correction for a regression case here: that would
# let the test pass by answer leakage rather than by exercising a real rule.
TERM_LEXICON = frozenset(
    {
        "深入",
        "气分证",
        "肺失宣降",
        "风寒挟湿",
        "风热挟湿",
        # Confirmed formula terms. Keep full phrases: a single rare character
        # is too ambiguous to auto-flag safely, while a one-character deletion
        # from a complete formula name is review-worthy.
        "半夏秫米汤",
        "半夏北秫米",
    }
)
CONFUSABLE_PAIRS = (("人", "入"), ("薷", "饮"), ("藁", "薬"))
UNEXPECTED_LAYOUT_MARKER_RE = re.compile(r"(?:^|\s)[>›»](?=\S)")
SHORT_CLINICAL_FRAGMENT_RE = re.compile(r"(?P<fragment>[鼻耳目口舌])(?=等症)")


@dataclass(frozen=True)
class OcrLine:
    page_number: int
    line_number: int
    text: str
    confidence: float


@dataclass(frozen=True)
class RiskFlag:
    rule_id: str
    page_number: int
    line_number: int
    text: str
    detail: str


def _delimiter_issue(text: str) -> str | None:
    for opening, closing in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
        if text.count(opening) != text.count(closing):
            return f"unbalanced_delimiter:{opening}{closing}"
    return None


def _one_edit_apart(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > MAX_TERM_EDIT_DISTANCE:
        return False
    return 1 - SequenceMatcher(a=left, b=right).ratio() <= 1 / max(len(left), len(right))


def _term_near_matches(text: str) -> list[str]:
    matches: list[str] = []
    for term in TERM_LEXICON:
        # Two-character medical terms are too collision-prone for fuzzy search
        # (for example, 鼻塞 must not be flagged as 鼻衄). They can still be
        # caught by confidence, context, or a future position-aware rule.
        if len(term) < 3:
            continue
        if term in text:
            continue
        for size in range(max(2, len(term) - 1), len(term) + 2):
            for start in range(0, max(0, len(text) - size + 1)):
                if _one_edit_apart(text[start : start + size], term):
                    matches.append(term)
                    break
            if term in matches:
                break
    return matches


def _confusable_word_matches(text: str) -> list[str]:
    matches: list[str] = []
    for original, replacement in CONFUSABLE_PAIRS:
        if original not in text:
            continue
        candidate = text.replace(original, replacement)
        if any(term in candidate for term in TERM_LEXICON):
            matches.append(f"{original}->{replacement}")
    return matches


def detect_risks(lines: list[OcrLine]) -> list[RiskFlag]:
    """Return review flags for OCR lines without altering their text."""

    flags: list[RiskFlag] = []
    for line in lines:
        if line.confidence < LOW_CONFIDENCE:
            flags.append(RiskFlag("low_confidence", line.page_number, line.line_number, line.text, f"confidence={line.confidence:.4f}"))
        if issue := _delimiter_issue(line.text):
            flags.append(RiskFlag("delimiter_balance", line.page_number, line.line_number, line.text, issue))
        if UNEXPECTED_LAYOUT_MARKER_RE.search(line.text):
            flags.append(RiskFlag("layout_marker", line.page_number, line.line_number, line.text, "unexpected leading layout marker"))
        if SHORT_CLINICAL_FRAGMENT_RE.search(line.text):
            flags.append(RiskFlag("short_clinical_fragment", line.page_number, line.line_number, line.text, "single-character clinical fragment before 等症"))
        for term in _term_near_matches(line.text):
            flags.append(RiskFlag("term_near_match", line.page_number, line.line_number, line.text, f"near confirmed term: {term}"))
        for pair in _confusable_word_matches(line.text):
            flags.append(RiskFlag("confusable_character", line.page_number, line.line_number, line.text, f"replacement creates known term: {pair}"))
    return flags
