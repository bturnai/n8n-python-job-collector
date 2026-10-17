"""Shared helpers for the n8n Python Code nodes.

n8n's native Python runner executes every Code node in a sandbox: no file or
network access, no classes, and only allow-listed standard-library modules. A
node cannot import another file either, so `scripts/sync.py` inlines this module
into each node's code before uploading it.

Several helpers reproduce JavaScript semantics on purpose. The nodes replace
JavaScript originals, and the de-duplication state (`seenIds`, `seenKeys`) and
the e-mail file names written by those originals must keep matching. JavaScript
strings are UTF-16, so slicing, indexOf and hashing count UTF-16 code units, and
its `\\s` / `trim()` use a slightly different whitespace set than Python.
"""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")

# Characters matched by JavaScript's \s and removed by String.prototype.trim().
JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
JS_WS_RUN = re.compile("[" + JS_WS + "]+")
JS_WS_EDGES = re.compile("^[" + JS_WS + "]+|[" + JS_WS + "]+\\Z")
LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def now_local():
    return datetime.now(TZ)


# strftime() imports the `time` module internally, which the sandbox blocks,
# so dates are formatted by hand.
def day_str(moment):
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def clock_str(moment):
    return f"{moment.hour:02d}{moment.minute:02d}{moment.second:02d}"


def iso_utc(moment):
    """Date.prototype.toISOString(): UTC, millisecond precision, 'Z' suffix."""
    utc = moment.astimezone(timezone.utc)
    return (f"{day_str(utc)}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
            f".{utc.microsecond // 1000:03d}Z")


def js_str(value):
    """String(value || '') - falsy values become an empty string."""
    if value is None or value is False or value == "" or value == 0:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def js_trim(text):
    return JS_WS_EDGES.sub("", text)


def collapse_ws(text):
    """text.replace(/\\s+/g, ' ')"""
    return JS_WS_RUN.sub(" ", text)


def _is_bmp(text):
    return all(ord(ch) < 0x10000 for ch in text)


def _utf16(text):
    return text.encode("utf-16-le", "surrogatepass")


def js_slice(text, start, end=None):
    """String.prototype.slice with UTF-16 offsets (start, end >= 0)."""
    if _is_bmp(text):
        return text[start:end]
    units = _utf16(text)
    stop = len(units) if end is None else min(len(units), 2 * end)
    return units[2 * start:stop].decode("utf-16-le", "surrogatepass")


def js_index_of(text, needle):
    """String.prototype.indexOf, returning a UTF-16 offset."""
    pos = text.find(needle)
    if pos < 0 or _is_bmp(text[:pos]):
        return pos
    return len(_utf16(text[:pos])) // 2


def js_hash(text):
    """The djb2-xor hash used for file names: h = ((h * 33) ^ unit) >>> 0."""
    h = 5381
    units = _utf16(text)
    for i in range(0, len(units), 2):
        h = ((h * 33) & 0xFFFFFFFF) ^ (units[i] | (units[i + 1] << 8))
    return f"{h:08x}"


def to_json(value):
    """JSON.stringify(value, null, 2)."""
    out = json.dumps(value, ensure_ascii=False, indent=2)
    # JSON.stringify escapes unpaired surrogates; json.dumps would emit them raw.
    return LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", out)


def dedupe_key(company, title):
    """Cross-source duplicate key: 'company|title', lower-case, single spaces."""
    key = js_str(company).lower() + "|" + js_str(title).lower()
    return js_trim(collapse_ws(key))


def decode_entities(text):
    """The small, fixed entity table the scraper has always used.

    The replacement order matters ('&amp;nbsp;' decodes differently in another
    order), so each JavaScript original's order is kept where it differed.
    """
    return (
        js_str(text)
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#039;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
    )


def split_state(items):
    """Separate the de-duplication state item from the data items.

    The workflow reads `latott.json` and appends it to the node's input. An
    "Extract from File" node puts the parsed object under `data`.
    """
    state = {"seenIds": [], "seenKeys": []}
    rest = []
    for item in items:
        data = item.get("json", {})
        candidate = data.get("data") if isinstance(data.get("data"), dict) else data
        if "seenIds" in candidate or "seenKeys" in candidate:
            state = {
                "seenIds": list(candidate.get("seenIds") or []),
                "seenKeys": list(candidate.get("seenKeys") or []),
            }
        else:
            rest.append(item)
    return state, rest
