# app/utils/amounts.py
from decimal import Decimal, InvalidOperation
import re
from typing import Any

_THOUS_SEP = re.compile(r"[,_\s']")       # commas, underscores, spaces, apostrophes
_LEADING_NON_DIGITS = re.compile(r"^[^\d+\-]*")  # strip currency symbols etc.
_VALID = re.compile(r"^[+\-]?\d+(\.\d+)?$")

def parse_amount(value: Any, places: int = 2) -> Decimal:
    """
    Accepts user input like '£1,000,000.5', '1_000_000', 1000000, etc.
    Returns a Decimal quantized to `places` (default 2).
    """
    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    elif isinstance(value, str):
        s = value.strip()
        s = _LEADING_NON_DIGITS.sub("", s)        # drop leading £ $ NGN etc.
        s = _THOUS_SEP.sub("", s)                 # remove thousand separators
        raw = s
    else:
        raise TypeError("amount must be str | int | float | Decimal")

    if not _VALID.match(raw):
        raise ValueError(f"Invalid amount: {value!r}")

    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {value!r}")

    q = Decimal("1") if places == 0 else Decimal("0." + "0" * places)
    return d.quantize(q)

def format_underscored(amount: Any, places: int = 2) -> str:
    """
    Formats number like 1_000_000 or 1_000_000.00.
    Uses comma-grouping on Decimal, then replaces commas with underscores.
    """
    d = parse_amount(amount, places=places)
    s = f"{d:,.{places}f}"   # Decimal supports comma grouping
    return s.replace(",", "_")
