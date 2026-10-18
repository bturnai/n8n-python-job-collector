"""Node "Kerelem mentese": records an application request sent as an e-mail reply.

The mail is stored raw; the evening task works out which job it refers to, so no
fixed keyword format is imposed on the reply.
"""
from common import day_str, iso_utc, js_hash, js_slice, js_str, now_local, to_json

TEXT_LIMIT = 8000


def mail_fingerprint(subject, date, text):
    """A short ID calculated from the mail. The same mail always gets the same ID.

    It goes into the file name, so a mail delivered twice overwrites its own
    file instead of creating a second request.
    """
    return js_hash(subject + "|" + date + "|" + js_slice(text, 0, 1000))


def main(items, now=None):
    # Time of saving. Only the tests pass `now`, to get a fixed time.
    if now is None:
        now = now_local()
    day = day_str(now)

    requests = []
    for item in items:
        mail = item["json"]
        subject = js_str(mail.get("subject"))
        text = js_str(mail.get("text"))
        mail_id = mail_fingerprint(subject, js_str(mail.get("date")), text)

        record = {
            "kert": iso_utc(now),  # when it was requested
            "datum": day,
            "forras": "email-valasz",  # source: e-mail reply
            "targy": subject,
            "szoveg": js_slice(text, 0, TEXT_LIMIT),
            "allapot": "uj",  # status: new
        }
        requests.append({"json": {
            "filename": f"kerelem_{day}_valasz_{mail_id}.json",
            "tartalom": to_json(record),
        }})
    return requests
