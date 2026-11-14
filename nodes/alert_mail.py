"""Node "Ertesito level kimentese" (NoFluffJobs and Indeed job alerts): stores each alert e-mail raw.

It works like linkedin_mail.py: the IMAP trigger hands over the mail, this node
turns it into one JSON file in `allasfigyelo/levelek/`. The 21:30 collector reads
those files and takes the jobs out of them (mail_parse.py). Keeping the raw mail
means a parser bug can be fixed later and the mail read again.

Same mail -> same file name, so a mail delivered twice overwrites its own file.

Example output file name: "indeed_2026-11-14_4c1d2e3f.json"
"""
from common import day_str, js_hash, js_slice, js_str, mail_html, now_local, sender_address, to_json

FINGERPRINT_TEXT_LENGTH = 2000
# An Indeed alert with 23 jobs is about 18 000 characters of text; a
# NoFluffJobs alert is about 25 000 characters of HTML. Room for more jobs.
TEXT_LIMIT = 60000
HTML_LIMIT = 60000


def source_of(sender):
    """Which job site sent the alert.

    Examples:
        source_of("notifications@nofluffjobs.com") -> "nofluffjobs"
        source_of("donotreply@jobalert.indeed.com") -> "indeed"
    """
    sender = sender.lower()
    if "nofluffjobs" in sender:
        return "nofluffjobs"
    if "indeed" in sender:
        return "indeed"
    return "egyeb"  # other: the parser skips it


def main(items, now=None):
    # Date of saving. Only the tests pass `now`, to get a fixed date.
    if now is None:
        now = now_local()
    day = day_str(now)

    saved_mails = []
    for item in items:
        mail = item["json"]
        subject = js_str(mail.get("subject"))
        text = js_str(mail.get("text"))
        received = ""
        if mail.get("date"):
            received = str(mail["date"])
        sender = sender_address(mail.get("from"))
        source = source_of(sender)

        fingerprint = js_hash(
            subject + "|" + received + "|" + js_slice(text, 0, FINGERPRINT_TEXT_LENGTH))

        record = {
            "datum": day,
            "forras": source,
            "erkezett": received,  # received
            "felado": sender,  # sender
            "targy": subject,
            "szoveg": js_slice(text, 0, TEXT_LIMIT),
            "html": js_slice(mail_html(mail), 0, HTML_LIMIT),
        }
        saved_mails.append({"json": {
            "filename": f"{source}_{day}_{fingerprint}.json",
            "tartalom": to_json(record),
        }})
    return saved_mails
