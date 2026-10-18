"""Node "Level kimentese" (LinkedIn job alerts): stores each alert e-mail raw.

The analysis is done later by a Claude Code task; this node only saves the mail.
The IMAP trigger does not mark mails as read, so it re-delivers them after every
restart. The file name is therefore derived from the mail's content: the same
mail always maps to the same name and is overwritten instead of duplicated.
"""
from common import day_str, js_hash, js_slice, js_str, now_local, to_json

# Length limits for the stored parts of the mail.
FINGERPRINT_TEXT_LENGTH = 2000
TEXT_LIMIT = 20000
HTML_LIMIT = 60000


def sender_address(sender):
    """The sender's e-mail address from the IMAP node's "from" field.

    The field usually looks like {"value": [{"address": "jobs@linkedin.com"}], "text": "..."}.
    """
    if not isinstance(sender, dict):
        return js_str(sender)

    addresses = sender.get("value") or []
    if len(addresses) > 0 and isinstance(addresses[0], dict) and addresses[0].get("address"):
        return addresses[0]["address"]
    if sender.get("text"):
        return sender["text"]
    # The original JavaScript printed an unknown object like this; kept for identical output.
    return "[object Object]"


def mail_html(mail):
    """The HTML version of the mail; the IMAP node calls it textHtml or html."""
    if mail.get("textHtml"):
        return js_str(mail["textHtml"])
    return js_str(mail.get("html"))


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

        # Same mail -> same fingerprint -> same file name (see the module docstring).
        fingerprint = js_hash(
            subject + "|" + received + "|" + js_slice(text, 0, FINGERPRINT_TEXT_LENGTH))

        record = {
            "datum": day,
            "erkezett": received,  # received
            "felado": sender_address(mail.get("from")),  # sender
            "targy": subject,
            "szoveg": js_slice(text, 0, TEXT_LIMIT),
            "html": js_slice(mail_html(mail), 0, HTML_LIMIT),
        }
        saved_mails.append({"json": {
            "filename": f"linkedin_{day}_{fingerprint}.json",
            "tartalom": to_json(record),
        }})
    return saved_mails
