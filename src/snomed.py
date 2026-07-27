"""
SNOMED CT / dm+d identifier validation and context-aware extraction from
measure SQL files.

Two independent checks distinguish a SNOMED concept identifier from a BNF code:

  1. Partition identifier. The two digits before the final digit must be
     "00" (core concept) or "10" (extension concept).
  2. Verhoeff check digit. The final digit validates the whole identifier.

Neither property holds for BNF codes, so a BNF prefix such as 1003020 fails.
Because both checks are also sensitive to transposed and dropped digits, a
failure is reported as a suspected typo rather than silently discarded.
"""

import re

# --- Verhoeff check digit ----------------------------------------------------

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(code):
    """True if the string of digits passes the Verhoeff checksum."""
    c = 0
    for i, ch in enumerate(reversed(code)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def validate_snomed(code):
    """
    Validate a SNOMED CT concept identifier.

    Returns (is_valid, reason), where reason is None when valid and a short
    human readable explanation otherwise.
    """
    if not code.isdigit():
        return False, "not numeric"
    if code.startswith("0"):
        return False, "leading zero"
    if not 6 <= len(code) <= 18:
        return False, f"length {len(code)} outside expected range 6-18"
    if code[-3:-1] not in ("00", "10"):
        return False, f"invalid partition identifier '{code[-3:-1]}'"
    if not verhoeff_valid(code):
        return False, "check digit failed"
    return True, None


# --- SQL scanning ------------------------------------------------------------

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)

# Columns whose literals are BNF codes and must never be treated as SNOMED.
# Add further column names here as new measures introduce them.
BNF_COLUMNS = ("bnf_code",)

_LITERAL_RE = re.compile(r"'(\d{4,20})'")


def _blank_comments(sql):
    """Replace comments with spaces so character offsets are preserved."""
    return _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), sql)


def _bnf_spans(sql):
    """
    Character ranges covering BNF code literals, handling:
        bnf_code = 'x'
        bnf_code IN ( ... )        including multiline lists
        bnf_code NOT IN ( ... )
        bnf_code LIKE 'x%'
    with optional table prefix and arbitrary whitespace.
    """
    spans = []
    col = "|".join(re.escape(c) for c in BNF_COLUMNS)
    pattern = re.compile(
        rf"(?:\w+\s*\.\s*)?(?:{col})\s*"
        rf"(?:=|<>|!=|(?:NOT\s+)?IN|(?:NOT\s+)?LIKE)\s*",
        re.I,
    )

    for m in pattern.finditer(sql):
        i = m.end()
        if i < len(sql) and sql[i] == "(":
            depth, j = 0, i
            while j < len(sql):
                if sql[j] == "(":
                    depth += 1
                elif sql[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            spans.append((i, j + 1))
        else:
            m2 = re.compile(r"\s*'[^']*'").match(sql, i)
            if m2:
                spans.append((i, m2.end()))
    return spans


def scan_sql(sql):
    """
    Extract SNOMED identifiers from measure SQL.

    Returns (snomed_codes, suspect_codes):
        snomed_codes  sorted list of valid identifiers, ready for $lookup
        suspect_codes list of (code, reason) for numeric literals outside any
                      BNF context that fail validation, i.e. probable typos
    """
    text = _blank_comments(sql)
    spans = _bnf_spans(text)

    def in_bnf(pos):
        return any(start <= pos < end for start, end in spans)

    snomed, suspect, seen = set(), [], set()

    for m in _LITERAL_RE.finditer(text):
        code, pos = m.group(1), m.start()
        if in_bnf(pos):
            continue
        ok, reason = validate_snomed(code)
        if ok:
            snomed.add(code)
        elif code not in seen:
            seen.add(code)
            suspect.append((code, reason))

    return sorted(snomed), suspect