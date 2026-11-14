"""Generate the n8n workflow that saves the job-alert e-mails (linkedinmail0001).

One IMAP trigger watches three senders. An If node then splits the mails:

  IMAP trigger (LinkedIn, NoFluffJobs, Indeed)
    -> "LinkedIn level?"
         yes -> linkedin_mail.py -> allasfigyelo/linkedin/<file>   (read by the
                evening Claude task, unchanged since 2026-10-18)
         no  -> alert_mail.py    -> allasfigyelo/levelek/<file>    (read by the
                21:30 collector, mail_parse.py)

The LinkedIn path keeps its node ids and names, so it works exactly as before.
The trigger keeps its id; sync.py carries its saved position in the mailbox
(lastMessageUid) over to the new name.

Usage:
  python scripts/workflow_mail.py --data-dir DIR --out FILE
  python scripts/sync.py push linkedinmail0001 --from FILE
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync  # noqa: E402

WORKFLOW_ID = "linkedinmail0001"
NAME = "Allasertesito levelek mentese (LinkedIn, NoFluffJobs, Indeed)"
IMAP_CREDENTIAL = {"id": "uZGvcpm7uuvjoGnF", "name": "IMAP account"}

LINKEDIN_SENDER = "jobalerts-noreply@linkedin.com"
# The senders of the real NoFluffJobs and Indeed alerts (2026-11-12 - 11-14).
NOFLUFFJOBS_SENDER = "notifications@nofluffjobs.com"
INDEED_SENDER = "donotreply@jobalert.indeed.com"


def imap_search():
    """Unread AND (LinkedIn OR (NoFluffJobs OR Indeed)). IMAP's OR takes exactly two parts.

    The IMAP library turns it into:
      UNSEEN OR (FROM "jobalerts-...") (OR (FROM "notifications@...") (FROM "donotreply@..."))
    """
    return json.dumps(["UNSEEN", ["OR", ["FROM", LINKEDIN_SENDER],
                                 ["OR", ["FROM", NOFLUFFJOBS_SENDER], ["FROM", INDEED_SENDER]]]])


def is_linkedin_node(x, y):
    """If node: true when the sender's address contains "linkedin.com".

    Same parameter format as the If node of the anyagkeszito0001 workflow (typeVersion 2.3).
    """
    return {"id": "mailif01", "name": "LinkedIn level?", "type": "n8n-nodes-base.if",
            "typeVersion": 2.3, "position": [x, y], "parameters": {
                "conditions": {
                    "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose",
                                "version": 3},
                    "conditions": [{"id": "c1", "leftValue": "={{ $json.from.value[0].address }}",
                                    "rightValue": "linkedin.com",
                                    "operator": {"type": "string", "operation": "contains"}}],
                    "combinator": "and"},
                "options": {}}}


def to_text_node(node_id, name, x, y):
    return {"id": node_id, "name": name, "type": "n8n-nodes-base.convertToFile", "typeVersion": 1.1,
            "position": [x, y], "parameters": {
                "operation": "toText", "sourceProperty": "tartalom",
                "options": {"encoding": "utf8", "fileName": "={{ $json.filename }}"}}}


def write_node(node_id, name, x, y, folder, code_node):
    return {"id": node_id, "name": name, "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1.1,
            "position": [x, y], "parameters": {
                "operation": "write", "options": {},
                "fileName": f"={folder}/{{{{ $('{code_node}').item.json.filename }}}}"}}


def build_workflow(data_dir):
    data_dir = data_dir.rstrip("/")
    nodes = [
        {"id": "imap0001", "name": "Allasertesito levelek figyelese",
         "type": "n8n-nodes-base.emailReadImap", "typeVersion": 2.2, "position": [0, 0],
         "credentials": {"imap": IMAP_CREDENTIAL},
         "parameters": {"postProcessAction": "read", "format": "resolved",
                        "options": {"customEmailConfig": imap_search(), "forceReconnect": 60,
                                    "trackLastMessageId": True}}},
        is_linkedin_node(240, 0),
        # LinkedIn: the nodes and ids of the original workflow.
        {"id": "licode01", "name": "Level kimentese", "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [480, -120],
         "parameters": {"language": "pythonNative", "pythonCode": sync.build("linkedin_mail")}},
        to_text_node("licnv01", "Szoveggé alakitas", 720, -120),
        write_node("liwrt01", "Fajl mentese", 960, -120, f"{data_dir}/linkedin", "Level kimentese"),
        # NoFluffJobs and Indeed.
        {"id": "alcode01", "name": "Ertesito level kimentese", "type": "n8n-nodes-base.code",
         "typeVersion": 2, "position": [480, 120],
         "parameters": {"language": "pythonNative", "pythonCode": sync.build("alert_mail")}},
        to_text_node("alcnv01", "Ertesito szoveggé alakitas", 720, 120),
        write_node("alwrt01", "Ertesito fajl mentese", 960, 120, f"{data_dir}/levelek",
                   "Ertesito level kimentese"),
    ]

    def link(target):
        return [{"node": target, "type": "main", "index": 0}]

    connections = {
        "Allasertesito levelek figyelese": {"main": [link("LinkedIn level?")]},
        # The If node has two outputs: [0] true, [1] false.
        "LinkedIn level?": {"main": [link("Level kimentese"), link("Ertesito level kimentese")]},
        "Level kimentese": {"main": [link("Szoveggé alakitas")]},
        "Szoveggé alakitas": {"main": [link("Fajl mentese")]},
        "Ertesito level kimentese": {"main": [link("Ertesito szoveggé alakitas")]},
        "Ertesito szoveggé alakitas": {"main": [link("Ertesito fajl mentese")]},
    }
    return {"id": WORKFLOW_ID, "name": NAME, "active": False, "nodes": nodes,
            "connections": connections,
            "settings": {"executionOrder": "v1", "binaryMode": "separate"}}


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="the allasfigyelo folder")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    workflow = build_workflow(args.data_dir)
    pathlib.Path(args.out).write_text(json.dumps([workflow], ensure_ascii=False, indent=1))
    print(f"{args.out}: {len(workflow['nodes'])} nodes")


if __name__ == "__main__":
    main(sys.argv[1:])
