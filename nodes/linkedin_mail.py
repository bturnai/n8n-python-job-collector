"""Node "Level kimentese" (LinkedIn job alerts): stores each alert e-mail raw.

The analysis is done later by a Claude Code task; this node only saves the mail.
The IMAP trigger does not mark mails as read, so it re-delivers them after every
restart. The file name is therefore derived from the mail's content: the same
mail always maps to the same name and is overwritten instead of duplicated.
"""
from common import day_str, js_hash, js_slice, js_str, now_local, to_json


def _sender(raw):
    if isinstance(raw, dict):
        values = raw.get("value") or []
        if values and isinstance(values[0], dict) and values[0].get("address"):
            return values[0]["address"]
        if raw.get("text"):
            return raw["text"]
        return "[object Object]"  # what String() printed for an unknown object
    return js_str(raw)


def main(items, now=None):
    day = day_str(now or now_local())
    out = []
    for item in items:
        mail = item["json"]
        subject = js_str(mail.get("subject"))
        received = str(mail["date"]) if mail.get("date") else ""
        text = js_str(mail.get("text"))
        mail_id = js_hash(subject + "|" + received + "|" + js_slice(text, 0, 2000))
        out.append({"json": {
            "filename": f"linkedin_{day}_{mail_id}.json",
            "tartalom": to_json({
                "datum": day, "erkezett": received, "felado": _sender(mail.get("from")),
                "targy": subject, "szoveg": js_slice(text, 0, 20000),
                "html": js_slice(js_str(mail.get("textHtml") or mail.get("html")), 0, 60000),
            }),
        }})
    return out
