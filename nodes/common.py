"""Shared helpers for the n8n Python Code nodes.

n8n's native Python runner executes every Code node in a sandbox: no file or
network access, no classes, and only allow-listed standard-library modules. A
node cannot import another file either, so `scripts/sync.py` copies this module
into each node's code before uploading it.

Why some helpers imitate JavaScript
-----------------------------------
These nodes replace JavaScript originals. The saved state (`seenIds`,
`seenKeys`) and the e-mail file names were produced by that JavaScript code, so
the Python code must produce exactly the same keys and names - otherwise old
jobs would look new and e-mails would be saved twice. JavaScript differs from
Python in two ways that matter here:

1. Text length. JavaScript counts a string in UTF-16 "code units". Most
   characters are 1 unit, but an emoji such as 😀 is 2 units. Python counts
   characters, so for Python 😀 is 1. Cutting a text to 2000 characters or
   hashing it therefore gives a different result if the text has emoji.
2. Whitespace. JavaScript's `\\s` and `trim()` accept a slightly different set of
   space characters than Python's.

The functions below are written so that they give the JavaScript result.
"""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")


# ---------------------------------------------------------------------------
# Dates and times
# ---------------------------------------------------------------------------
# strftime() would be the usual way to format dates, but it imports the `time`
# module internally, which the sandbox blocks. So dates are formatted by hand.
# (The TZ environment variable has no effect in the sandbox either, so the time
# zone is always given explicitly.)

def now_local():
    """The current time in Budapest."""
    return datetime.now(TZ)


def day_str(moment):
    """Example: 2026-10-17 21:30 -> "2026-10-17"  (:02d means at least 2 digits, 0-padded)"""
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def clock_str(moment):
    """Example: 21:30:05 -> "213005" """
    return f"{moment.hour:02d}{moment.minute:02d}{moment.second:02d}"


def iso_utc(moment):
    """Like JavaScript's toISOString(): UTC time, milliseconds, "Z" at the end.

    Example: 2026-10-17 21:30:05.123 in Budapest (UTC+2) -> "2026-10-17T19:30:05.123Z"
    """
    utc = moment.astimezone(timezone.utc)
    milliseconds = utc.microsecond // 1000
    return (f"{day_str(utc)}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
            f".{milliseconds:03d}Z")


# ---------------------------------------------------------------------------
# Values as text
# ---------------------------------------------------------------------------

def js_str(value):
    """Like JavaScript's String(value || ''): empty-like values become "".

    Examples: None -> "",  0 -> "",  "abc" -> "abc",  12.0 -> "12",  True -> "true"
    """
    if value is None or value is False or value == "" or value == 0:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # JavaScript prints 12.0 as "12"
    return str(value)


# ---------------------------------------------------------------------------
# Whitespace, the JavaScript way
# ---------------------------------------------------------------------------
# The characters JavaScript treats as whitespace: tab, newline, the usual space,
# the non-breaking space ( ), several typographic spaces, and the byte order
# mark (﻿). Python's own list differs slightly (e.g. it includes \u0085).
JS_WHITESPACE = "\t\n\v\f\r    -     　﻿"
JS_WHITESPACE_RUN = re.compile("[" + JS_WHITESPACE + "]+")
# Whitespace at the start (^) or at the very end (\Z) of the text.
JS_WHITESPACE_AT_ENDS = re.compile("^[" + JS_WHITESPACE + "]+|[" + JS_WHITESPACE + "]+\\Z")


def collapse_ws(text):
    """Replace every run of whitespace with one space: "a \\n\\t b" -> "a b" """
    return JS_WHITESPACE_RUN.sub(" ", text)


def js_trim(text):
    """Remove whitespace from both ends: "  a b  " -> "a b" """
    return JS_WHITESPACE_AT_ENDS.sub("", text)


# ---------------------------------------------------------------------------
# Text length, the JavaScript way (UTF-16 code units)
# ---------------------------------------------------------------------------

def has_only_simple_characters(text):
    """True if no character needs 2 UTF-16 units (no emoji and similar).

    Such text has the same length in JavaScript and Python, so the normal Python
    operations can be used.
    """
    for character in text:
        if ord(character) > 0xFFFF:
            return False
    return True


def to_utf16_units(text):
    """The text as a list of UTF-16 code units.

    Example: to_utf16_units("a😀") -> [97, 55357, 56832]   ("a" is 1 unit, 😀 is 2)
    """
    data = text.encode("utf-16-le", "surrogatepass")
    units = []
    # Each unit is 2 bytes; "le" (little-endian) means the low byte comes first.
    for i in range(0, len(data), 2):
        units.append(data[i] + data[i + 1] * 256)
    return units


def from_utf16_units(units):
    """The reverse of to_utf16_units: [97, 55357, 56832] -> "a😀" """
    data = bytearray()
    for unit in units:
        data.append(unit % 256)   # low byte
        data.append(unit // 256)  # high byte
    # "surrogatepass" allows half an emoji, which slicing can produce.
    return bytes(data).decode("utf-16-le", "surrogatepass")


def js_slice(text, start, end=None):
    """Like JavaScript's text.slice(start, end), counting UTF-16 units.

    Example: js_slice("ab😀c", 0, 4) -> "ab😀"  (😀 counts as 2)
    """
    if has_only_simple_characters(text):
        return text[start:end]
    units = to_utf16_units(text)
    return from_utf16_units(units[start:end])


def js_index_of(text, needle):
    """Like JavaScript's text.indexOf(needle): the position in UTF-16 units, or -1.

    Example: js_index_of("😀 SQL", "SQL") -> 3   (Python's find() would say 2)
    """
    position = text.find(needle)
    if position < 0:
        return -1
    units_before = 0
    for character in text[:position]:
        if ord(character) > 0xFFFF:
            units_before += 2
        else:
            units_before += 1
    return units_before


def js_hash(text):
    """The short hash the JavaScript version used in file names (djb2 with XOR).

    Start from 5381; for every UTF-16 unit: multiply by 33, keep 32 bits, XOR
    the unit. The result is written as 8 hexadecimal digits.
    Example: js_hash("") -> "00001505"   (5381 in hexadecimal)
    """
    value = 5381
    for unit in to_utf16_units(text):
        value = (value * 33) % 4294967296  # keep 32 bits, as JavaScript's >>> 0 did
        value = value ^ unit               # ^ is bitwise XOR
    return f"{value:08x}"  # 08x: hexadecimal, at least 8 digits, 0-padded


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
# After slicing, a text can end in half an emoji (a "lone surrogate").
LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def escape_surrogate(match):
    """Half an emoji as the \\uXXXX escape JavaScript writes: "\\ud83d" """
    return f"\\u{ord(match.group()):04x}"


def to_json(value):
    """Like JavaScript's JSON.stringify(value, null, 2): indented JSON text."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    # JavaScript escapes half emoji; Python would write them raw, which then
    # fails when the text is saved as UTF-8.
    return LONE_SURROGATE.sub(escape_surrogate, text)


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def dedupe_key(company, title):
    """The key that finds the same job across sources: "company|title".

    Lower-case, with single spaces. Example:
    dedupe_key("Acme  Kft.", "Data Analyst") -> "acme kft.|data analyst"
    """
    key = js_str(company).lower() + "|" + js_str(title).lower()
    return js_trim(collapse_ws(key))


def decode_entities(text):
    """Turn the common HTML entities back into characters: "R&amp;D" -> "R&D".

    The order of the replacements matters ("&amp;nbsp;" gives a different result
    in another order), so it matches the original version exactly.
    """
    text = js_str(text)
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&nbsp;", " ")
    return text


def split_state(items):
    """Separate the saved de-duplication state from the other input items.

    The workflow reads `latott.json` and adds it to the node's input as one more
    item. The "Extract from File" node puts the file's content under "data":
        {"json": {"data": {"seenIds": [...], "seenKeys": [...]}}}
    Returns (state, the other items).
    """
    state = {"seenIds": [], "seenKeys": []}
    other_items = []
    for item in items:
        fields = item.get("json", {})

        # The state may be under "data" (from the file node) or directly in the item.
        if isinstance(fields.get("data"), dict):
            content = fields["data"]
        else:
            content = fields

        if "seenIds" in content or "seenKeys" in content:
            state = {
                "seenIds": list(content.get("seenIds") or []),
                "seenKeys": list(content.get("seenKeys") or []),
            }
        else:
            other_items.append(item)
    return state, other_items
