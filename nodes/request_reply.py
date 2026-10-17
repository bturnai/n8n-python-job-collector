"""Node "Kerelem mentese": records an application request sent as an e-mail reply.

The mail is stored raw; the evening task works out which job it refers to, so no
fixed keyword format is imposed on the reply.
"""
from common import day_str, iso_utc, js_hash, js_slice, js_str, now_local, to_json


def main(items, now=None):
    moment = now or now_local()
    day = day_str(moment)
    out = []
    for item in items:
        mail = item["json"]
        subject = js_str(mail.get("subject"))
        text = js_str(mail.get("text"))
        mail_id = js_hash(subject + "|" + js_str(mail.get("date")) + "|" + js_slice(text, 0, 1000))
        out.append({"json": {
            "filename": f"kerelem_{day}_valasz_{mail_id}.json",
            "tartalom": to_json({
                "kert": iso_utc(moment), "datum": day, "forras": "email-valasz",
                "targy": subject, "szoveg": js_slice(text, 0, 8000), "allapot": "uj",
            }),
        }})
    return out
