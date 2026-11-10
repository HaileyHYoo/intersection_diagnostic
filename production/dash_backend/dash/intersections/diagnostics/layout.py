"""Labelled lines for the report text (methodology owner's review: the main point at a glance).

The code-written answers put each part on its own line, starting with a fixed label. An LLM re-wording must keep
the labels (checked as required wording); `lines()` restores the line breaks if it ran them together.
"""
from __future__ import annotations

import re

D001_LABELS = ["What the data show:", "Possible explanations (not demonstrated by these data):"]
D002_LABELS = ["Largest values:", "By approach:", "Overall:", "Coverage:"]


def lines(text: str, labels: list[str]) -> str:
    """One label per line, in the order written; text before the first label stays on its own line."""
    out = str(text or "")
    for label in labels:
        out = re.sub(r"\s*" + re.escape(label), "\n" + label, out, count=1)
    return "\n".join(x.strip() for x in out.strip().split("\n") if x.strip())


def keep_code_lines(worded: str, code: str, labels: list[str], fixed: list[str]) -> str:
    """The worded text with the lines starting with a label in `fixed` replaced by the code's own lines."""
    worded, code = lines(worded, labels), lines(code, labels)
    own = {label: line for line in code.split("\n") for label in fixed if line.startswith(label)}
    out = [line for line in worded.split("\n") if not any(line.startswith(label) for label in fixed)]
    return "\n".join(out + [own[label] for label in fixed if label in own])
