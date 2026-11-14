"""Generate the n8n workflow that saves NoFluffJobs and Indeed job-alert e-mails.

It is a copy of the LinkedIn mail workflow (linkedinmail0001) with another
sender filter and another folder: IMAP trigger -> alert_mail.py -> one JSON file
per mail in <data-dir>/levelek/. The 21:30 collector reads that folder
(mail_parse.py).

The IMAP filter takes only unread mails from the two alert senders, and marks
them read after saving, like the LinkedIn workflow does.

Usage:
  python scripts/workflow_alert_mail.py --data-dir DIR --out FILE
  python scripts/sync.py push ertesitomail0001 --from FILE
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync  # noqa: E402

WORKFLOW_ID = "ertesitomail0001"
NAME = "NoFluffJobs + Indeed ertesitok - levelek mentese"
FOLDER_ID = "BDXMcf1exxSGKONq"  # the "állásfigyelő" folder in the n8n UI
IMAP_CREDENTIAL = {"id": "uZGvcpm7uuvjoGnF", "name": "IMAP account"}  # same as LinkedIn's

# The senders of the real alerts (2026-11-12 - 11-14).
SENDERS = ["notifications@nofluffjobs.com", "donotreply@jobalert.indeed.com"]


def imap_search():
    """The IMAP search: unread AND (from sender 1 OR from sender 2)."""
    return json.dumps(["UNSEEN", ["OR", ["FROM", SENDERS[0]], ["FROM", SENDERS[1]]]])


def build_workflow(data_dir):
    folder = data_dir.rstrip("/") + "/levelek"
    nodes = [
        {"name": "Ertesito levelek figyelese", "type": "n8n-nodes-base.emailReadImap",
         "typeVersion": 2.2, "position": [0, 0], "credentials": {"imap": IMAP_CREDENTIAL},
         "parameters": {"postProcessAction": "read", "format": "resolved",
                        "options": {"customEmailConfig": imap_search(), "forceReconnect": 60,
                                    "trackLastMessageId": True}}},
        {"name": "Ertesito level kimentese", "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [240, 0],
         "parameters": {"language": "pythonNative", "pythonCode": sync.build("alert_mail")}},
        {"name": "Szoveggé alakitas", "type": "n8n-nodes-base.convertToFile", "typeVersion": 1.1,
         "position": [480, 0],
         "parameters": {"operation": "toText", "sourceProperty": "tartalom",
                        "options": {"encoding": "utf8", "fileName": "={{ $json.filename }}"}}},
        {"name": "Fajl mentese", "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1.1,
         "position": [720, 0],
         "parameters": {"operation": "write", "options": {},
                        "fileName": f"={folder}/{{{{ $('Ertesito level kimentese').item.json.filename }}}}"}},
    ]
    for index, node in enumerate(nodes):
        node["id"] = f"{WORKFLOW_ID[:8]}-{index:04d}"

    connections = {}
    order = ["Ertesito levelek figyelese", "Ertesito level kimentese", "Szoveggé alakitas", "Fajl mentese"]
    for index in range(len(order) - 1):
        connections[order[index]] = {"main": [[{"node": order[index + 1], "type": "main", "index": 0}]]}

    return {"id": WORKFLOW_ID, "name": NAME, "active": False, "nodes": nodes,
            "connections": connections, "parentFolderId": FOLDER_ID,
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
