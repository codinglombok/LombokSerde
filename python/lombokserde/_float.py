"""Canonical float rendering, identical in every port (SPEC section 4).

Digits are the shortest decimal that roundtrips to the same binary64,
obtained from repr() (CPython's shortest-roundtrip formatter), re-rendered
with the pinned presentation rules.
"""

from __future__ import annotations

import math


def render_float(f: float) -> str:
    """Render a finite binary64 per the pinned presentation rules."""
    if f == 0.0:
        return "-0.0" if math.copysign(1.0, f) < 0 else "0.0"
    sign = "-" if math.copysign(1.0, f) < 0 else ""
    digits, exp = shortest_digits(f)
    n = len(digits)
    if exp >= 21 or exp <= -7:
        mant = digits if n == 1 else digits[0] + "." + digits[1:]
        esign = "+" if exp >= 0 else "-"
        return f"{sign}{mant}e{esign}{abs(exp)}"
    if exp >= n - 1:
        return f"{sign}{digits}{'0' * (exp - (n - 1))}.0"
    if exp >= 0:
        e = exp + 1
        return f"{sign}{digits[:e]}.{digits[e:]}"
    return f"{sign}0.{'0' * (-exp - 1)}{digits}"


def shortest_digits(f: float) -> tuple[str, int]:
    """Shortest-roundtrip digits + decimal exponent of the first digit."""
    s = repr(abs(f))
    if "e" in s or "E" in s:
        mant, _, es = s.lower().partition("e")
        exp = int(es)
    else:
        mant, exp = s, 0
    if "." in mant:
        ip, _, fp = mant.partition(".")
    else:
        ip, fp = mant, ""
    total = ip + fp
    stripped = total.lstrip("0")
    if stripped == "":
        return ("0", 0)
    first_pos = len(total) - len(stripped)
    exp10 = exp - len(fp) + len(total) - 1 - first_pos
    return (stripped.rstrip("0"), exp10)
