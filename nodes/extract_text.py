"""Node "Hirdetes-szoveg kinyerese": plain text from a profession.hu job page.

Input: one item per selected job - the job card fields merged with the
downloaded detail page (`data`). Output: the job card plus `techs` (the
"required technologies" block) and `description` (the posting text, capped).
"""
import re

from common import collapse_ws, js_index_of, js_slice, js_trim

HTTP_FIELDS = ("data", "body", "error")
DESCRIPTION_LIMIT = 2200
TECHS_LIMIT = 300


def strip_html(html):
    text = re.sub(r"<script[\s\S]*?</script>", " ", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
            .replace("&#039;", "'").replace("&#39;", "'")
            .replace("&lt;", "<").replace("&gt;", ">"))
    return js_trim(collapse_ws(text))


def _find_heading(text, plain, accented):
    pos = js_index_of(text, plain)
    return pos if pos >= 0 else js_index_of(text, accented)


def main(items):
    out = []
    for item in items:
        data = item["json"]
        meta = {key: value for key, value in data.items() if key not in HTTP_FIELDS}
        text = strip_html(data.get("data") or data.get("body") or "")

        techs = ""
        start = _find_heading(text, "Elvart technologiak", "Elvárt technológiák")
        if start >= 0:
            techs = js_slice(text, start, start + TECHS_LIMIT)

        description = text
        start = _find_heading(text, "Allas leirasa", "Állás leírása")
        if start >= 0:
            description = js_slice(text, start)
        description = js_slice(description, 0, DESCRIPTION_LIMIT)

        out.append({"json": {**meta, "techs": techs,
                             "description": description or "(nem sikerult kinyerni)"}})
    return out
