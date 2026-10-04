"""Transformation engine — turns one Excel row into the string a form field needs.

Pure: no FastAPI, no LLM, no document-format knowledge. A *spec* is a small dict
(`{"type": "amount_in_words", "source": "Penal Sum"}`) naming a transform from
CATALOG plus its parameters. The LLM may only choose from CATALOG; it never
writes conversion logic, so a spec can only do things that are tested here.

Two error classes, deliberately distinct:
- TransformSpecError: the spec itself is bad (unknown type, bad params, a column
  that doesn't exist). A request bug — callers reject the whole request.
- TransformError: this row's data can't be converted (blank, unparseable,
  ambiguous). Callers report it for that row only. Never guess: a visible error
  beats a wrong value on a legal document.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable


class TransformError(Exception):
    """This row's data can't be converted."""


class TransformSpecError(TransformError):
    """The transform spec itself is invalid."""


@dataclass(frozen=True)
class Transform:
    name: str
    required: frozenset[str]
    optional: frozenset[str]
    apply: Callable[[dict[str, Any], dict[str, str]], str]
    # Columns the spec reads from the row — used for column validation and
    # for deciding whether a bulk row is blank (skipped) before transforms run.
    referenced_columns: Callable[[dict[str, Any]], set[str]]
    # Extra spec checks beyond params/columns (e.g. date pattern whitelist).
    check_spec: Callable[[dict[str, Any]], None] = lambda spec: None
    # Shown to the LLM in the mapper prompt (generated from CATALOG so the two
    # can never drift): what it does, and one valid example spec.
    description: str = ""
    example: dict[str, Any] = field(default_factory=dict)


CATALOG: dict[str, Transform] = {}


def register(
    name: str,
    required: set[str],
    optional: set[str] | None = None,
    referenced_columns: Callable[[dict[str, Any]], set[str]] | None = None,
    check_spec: Callable[[dict[str, Any]], None] | None = None,
    description: str = "",
    example: dict[str, Any] | None = None,
):
    """Register a transform function in CATALOG under `name`."""

    def decorator(fn):
        CATALOG[name] = Transform(
            name=name,
            required=frozenset(required),
            optional=frozenset(optional or ()),
            apply=fn,
            referenced_columns=referenced_columns or (lambda spec: {spec["source"]}),
            check_spec=check_spec or (lambda spec: None),
            description=description,
            example=example or {},
        )
        return fn

    return decorator


def _check_source_type(spec: dict[str, Any]) -> None:
    """`source` must be a string column name — a list/dict would otherwise crash
    set arithmetic or dict lookups later instead of being rejected cleanly."""
    if "source" in spec and not isinstance(spec["source"], str):
        raise TransformSpecError(f"'source' must be a column name string, got {type(spec['source']).__name__}")


def validate_spec(spec: Any, columns: list[str]) -> None:
    """Raise TransformSpecError unless `spec` is a well-formed spec over `columns`."""
    transform = _lookup(spec)
    _check_source_type(spec)
    params = set(spec) - {"type"}
    missing = transform.required - params
    if missing:
        raise TransformSpecError(f"'{transform.name}' is missing required param(s): {sorted(missing)}")
    extra = params - transform.required - transform.optional
    if extra:
        raise TransformSpecError(f"'{transform.name}' got unexpected param(s): {sorted(extra)}")
    transform.check_spec(spec)
    unknown = transform.referenced_columns(spec) - set(columns)
    if unknown:
        raise TransformSpecError(f"'{transform.name}' references unknown column(s): {sorted(unknown)}")


def apply_transform(spec: Any, row: dict[str, str]) -> str:
    """Apply `spec` to `row`. Spec shape is checked here; column existence is the
    caller's job via validate_spec (a missing column in `row` is a data matter)."""
    transform = _lookup(spec)
    _check_source_type(spec)
    params = set(spec) - {"type"}
    if (transform.required - params) or (params - transform.required - transform.optional):
        validate_spec(spec, list(row))  # raises the precise TransformSpecError
    transform.check_spec(spec)
    return transform.apply(spec, row)


def _lookup(spec: Any) -> Transform:
    if not isinstance(spec, dict):
        raise TransformSpecError(f"transform spec must be an object, got {type(spec).__name__}")
    name = spec.get("type")
    if not isinstance(name, str) or name not in CATALOG:
        raise TransformSpecError(f"unknown transform type: {name!r}")
    return CATALOG[name]


_MAX_ECHO = 40


def _shown(raw: Any) -> str:
    """A cell value as it appears in an error message, truncated so a long (or
    sensitive) cell is never echoed back wholesale in an API response."""
    text = repr(raw)
    return text if len(text) <= _MAX_ECHO else text[: _MAX_ECHO - 1] + "…"


_MONEY_RE = re.compile(r"^\$?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?$")
_MAX_AMOUNT = Decimal(10) ** 15  # one quadrillion — exclusive upper bound
_CENT = Decimal("0.01")


def parse_money(raw: str) -> Decimal:
    """Parse a dollar amount strictly, as an exact Decimal (never a binary float).

    Accepts an optional leading '$' and correctly grouped commas. Anything
    ambiguous raises TransformError rather than being guessed or rounded:
    negatives, accounting parentheses, odd comma grouping, scientific notation,
    more than 2 non-zero decimal places (e.g. a formula cell's float artifact
    like '1234.5600000000001'), and amounts >= one quadrillion.
    """
    text = (raw or "").strip()
    match = _MONEY_RE.match(text)
    if not match:
        raise TransformError(f"not a valid dollar amount: {_shown(raw)}")
    whole, fraction = match.group(1).replace(",", ""), match.group(2) or ""
    if fraction[2:].strip("0"):
        raise TransformError(f"amount has more than 2 decimal places: {_shown(raw)}")
    value = Decimal(f"{whole}.{fraction[:2].ljust(2, '0')}")
    if value >= _MAX_AMOUNT:
        raise TransformError(f"amount is too large: {_shown(raw)}")
    return value.quantize(_CENT)


@register(
    "copy",
    required={"source"},
    description="Copy the column's value unchanged.",
    example={"type": "copy", "source": "Principal Name"},
)
def _copy(spec: dict[str, Any], row: dict[str, str]) -> str:
    """Today's behaviour: the raw cell value; absent/blank → ''."""
    return row.get(spec["source"], "")


_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = (
    (10**12, "trillion"),
    (10**9, "billion"),
    (10**6, "million"),
    (10**3, "thousand"),
)


def _below_thousand(n: int) -> str:
    """Words for 1..999 (no 'and': 101 -> 'one hundred one')."""
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} hundred")
        n %= 100
    if n >= 20:
        tens, ones = _TENS[n // 10], n % 10
        parts.append(f"{tens}-{_ONES[ones]}" if ones else tens)
    elif n > 0:
        parts.append(_ONES[n])
    return " ".join(parts)


def _int_to_words(n: int) -> str:
    """Words for a non-negative integer below one quadrillion."""
    if n == 0:
        return "zero"
    parts = []
    for size, name in _SCALES:
        if n >= size:
            parts.append(f"{_below_thousand(n // size)} {name}")
            n %= size
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


@register(
    "amount_in_words",
    required={"source"},
    description=(
        "Write a dollar amount in words, e.g. 1200000 -> "
        "'one million two hundred thousand and 00/100 dollars'."
    ),
    example={"type": "amount_in_words", "source": "Penal Sum"},
)
def _amount_in_words(spec: dict[str, Any], row: dict[str, str]) -> str:
    """USD amount in lowercase words with cents as a fraction over 100, e.g.
    '1200000' -> 'one million two hundred thousand and 00/100 dollars'."""
    amount = parse_money(row.get(spec["source"], ""))
    whole, cents = divmod(int(amount * 100), 100)
    return f"{_int_to_words(whole)} and {cents:02d}/100 dollars"


@register(
    "currency",
    required={"source"},
    description="Format a dollar amount with $ and commas, e.g. 1200000 -> '$1,200,000.00'.",
    example={"type": "currency", "source": "Penal Sum"},
)
def _currency(spec: dict[str, Any], row: dict[str, str]) -> str:
    """USD with grouping and exactly 2 decimals, e.g. '1200000' -> '$1,200,000.00'.
    Formats the Decimal directly — never via a binary float."""
    return f"${parse_money(row.get(spec['source'], '')):,.2f}"


_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()
_ISO_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?: 00:00:00)?$")
# Directives a date_format pattern may use; any other '%' is rejected. Rendered
# by our own code (not the C library) so output is locale- and platform-independent.
_DATE_TOKEN_RE = re.compile(r"%-?[a-zA-Z%]?")
_DATE_DIRECTIVES = {
    "%Y": lambda d: f"{d.year:04d}",
    "%y": lambda d: f"{d.year % 100:02d}",
    "%m": lambda d: f"{d.month:02d}",
    "%-m": lambda d: str(d.month),
    "%d": lambda d: f"{d.day:02d}",
    "%-d": lambda d: str(d.day),
    "%B": lambda d: _MONTHS[d.month - 1],
    "%b": lambda d: _MONTHS[d.month - 1][:3],
}


def _check_date_format(spec: dict[str, Any]) -> None:
    pattern = spec["format"]
    if not isinstance(pattern, str) or not pattern:
        raise TransformSpecError("date_format 'format' must be a non-empty string")
    for token in _DATE_TOKEN_RE.findall(pattern):
        if token.startswith("%") and token not in _DATE_DIRECTIVES:
            raise TransformSpecError(
                f"unsupported date directive {token!r}; allowed: {sorted(_DATE_DIRECTIVES)}"
            )


def _parse_iso_date(raw: str) -> date:
    match = _ISO_DATE_RE.match((raw or "").strip())
    if not match:
        raise TransformError(f"not an ISO date (YYYY-MM-DD): {_shown(raw)}")
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError:
        raise TransformError(f"not a real calendar date: {_shown(raw)}") from None


@register(
    "date_format",
    required={"source", "format"},
    check_spec=_check_date_format,
    description=(
        "Re-format an ISO date (YYYY-MM-DD). 'format' may only use %Y %y %m %-m %d %-d "
        "%B %b plus literal text, e.g. '%B %-d, %Y' -> 'January 5, 2024'."
    ),
    example={"type": "date_format", "source": "Effective Date", "format": "%B %-d, %Y"},
)
def _date_format(spec: dict[str, Any], row: dict[str, str]) -> str:
    """Re-render an ISO date with a whitelisted pattern, e.g. '2024-01-05' with
    '%B %-d, %Y' -> 'January 5, 2024'. Slash/text dates are ambiguous → error."""
    parsed = _parse_iso_date(row.get(spec["source"], ""))
    return _DATE_TOKEN_RE.sub(
        lambda m: _DATE_DIRECTIVES[m.group()](parsed) if m.group().startswith("%") else m.group(),
        spec["format"],
    )


_JOIN_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([^{}]+)\}")


def _check_join_template(spec: dict[str, Any]) -> None:
    template = spec["template"]
    if not isinstance(template, str) or not template.strip():
        raise TransformSpecError("join 'template' must be a non-empty string")
    # Whatever the token regex doesn't consume must contain no stray braces.
    if "{" in _JOIN_TOKEN_RE.sub("", template) or "}" in _JOIN_TOKEN_RE.sub("", template):
        raise TransformSpecError(f"join template has unbalanced braces: {template!r}")


def _join_columns(spec: dict[str, Any]) -> set[str]:
    return {m.group(1) for m in _JOIN_TOKEN_RE.finditer(spec["template"]) if m.group(1)}


@register(
    "join",
    required={"template"},
    referenced_columns=_join_columns,
    check_spec=_check_join_template,
    description=(
        "Combine several columns into one value. 'template' uses {Exact Column Name} "
        "tokens, e.g. '{First Name} {Last Name}'."
    ),
    example={"type": "join", "template": "{First Name} {Last Name}"},
)
def _join(spec: dict[str, Any], row: dict[str, str]) -> str:
    """Combine columns into one value, e.g. '{First} {Last}' -> 'John Doe'.
    Tokens are exact column names (parsed with our own regex, since str.format
    breaks on names containing '.', '[', ':' or '!'); '{{' / '}}' are literal
    braces. Blank pieces become '' and whitespace runs collapse."""

    def render(match: re.Match) -> str:
        if match.group(0) == "{{":
            return "{"
        if match.group(0) == "}}":
            return "}"
        return row.get(match.group(1), "")

    return " ".join(_JOIN_TOKEN_RE.sub(render, spec["template"]).split())


def normalise_column_case(spec: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """Return a copy of `spec` with column references fixed to the real columns'
    exact case (LLMs often change case). Unknown columns are left untouched so
    validate_spec rejects them; the input is never mutated."""
    by_lower = {c.lower(): c for c in columns}
    fixed = dict(spec)
    if isinstance(fixed.get("source"), str):
        fixed["source"] = by_lower.get(fixed["source"].lower(), fixed["source"])
    if isinstance(fixed.get("template"), str):

        def fix(match: re.Match) -> str:
            name = match.group(1)
            if name is None:  # a '{{' or '}}' literal
                return match.group(0)
            return "{" + by_lower.get(name.lower(), name) + "}"

        fixed["template"] = _JOIN_TOKEN_RE.sub(fix, fixed["template"])
    return fixed
