"""Editing a queued proposal field by field (Phase 7 package F, D-61). Pure Python: no DB, web or LLM imports.

A `field_path` is the path the engine's findings use: "invoice_no", "lines[1].taxable_value", "totals.grand_total", and for a Tally
proposal "narration", "lines[0].ledger_id". Setting a path never changes the original: the caller passes a copy of the current payload.

An extraction field is an object {value, page, bbox, confidence}. Editing it by its path ("invoice_no") sets the value and marks the
field as confirmed by the accountant: confidence 1, the old page and box are kept, page 1 when there was none (the check wants a source
for a field read by a model; the audit log keeps who changed what).
"""

import copy
import re
from typing import Any

_TOKEN = re.compile(r"(?:\.?([A-Za-z_][A-Za-z0-9_]*))|\[(\d+)\]")


class PathError(ValueError):
    """The path does not point into the payload."""


def parse_path(path: str) -> list[str | int]:
    if not isinstance(path, str) or not path.strip():
        raise PathError("The field path is empty.")
    out: list[str | int] = []
    pos = 0
    text = path.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or (pos == 0 and text[0] in ".["):
            raise PathError(f"'{path}' is not a valid field path.")
        out.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        pos = m.end()
    return out


def _confirmed(old: Any, value: str | None) -> dict:
    old = old if isinstance(old, dict) else {}
    page = old.get("page")
    return {"value": value, "page": page if isinstance(page, int) and page >= 1 else 1, "bbox": old.get("bbox"), "confidence": "1"}


def set_path(payload: dict, path: str, value: Any) -> tuple[dict, Any]:
    """(a copy of the payload with the value set, the old value). A path that ends at an extraction field object sets its value."""
    tokens = parse_path(path)
    new = copy.deepcopy(payload)
    node: Any = new
    for tok in tokens[:-1]:
        try:
            node = node[tok]
        except (KeyError, IndexError, TypeError):
            raise PathError(f"'{path}' does not exist in this document.") from None
    last = tokens[-1]
    try:
        old = node[last]
    except (KeyError, IndexError, TypeError):
        if isinstance(last, int) or not isinstance(node, dict):
            raise PathError(f"'{path}' does not exist in this document.") from None
        old = None
    if isinstance(old, dict) and "value" in old:
        if value is not None and not isinstance(value, str):
            raise PathError(f"'{path}' takes text as printed (or nothing), not a {type(value).__name__}.")
        node[last] = _confirmed(old, None if value is None or not value.strip() else value.strip())
        return new, old.get("value")
    node[last] = value
    return new, old


def value_at(payload: dict, path: str) -> Any:
    node: Any = payload
    for tok in parse_path(path):
        try:
            node = node[tok]
        except (KeyError, IndexError, TypeError):
            return None
    return node.get("value") if isinstance(node, dict) and "value" in node else node
