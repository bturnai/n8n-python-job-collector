"""Generate the n8n workflow of the daily job collector, with the Python nodes.

n8n handles triggers, HTTP downloads and file I/O; every transformation is a
Python Code node built from `nodes/` by `sync.build`. Two n8n features the
JavaScript version relied on do not exist for Python nodes, so the graph makes
them explicit:

* `$getWorkflowStaticData` (state kept between runs) -> the de-duplication state
  lives in `<data-dir>/allapot/latott.json`, read at the start and written at
  the end of the run.
* `$('Other node')` (reading another node's output) -> Merge nodes combine each
  HTTP response with the item that requested it, by position.

Usage:
  python scripts/workflow_collector.py --data-dir DIR --out FILE
      [--id ID] [--name NAME] [--webhook-path PATH] [--no-schedule]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync  # noqa: E402

# An honest client name, not a browser imitation: since 2026-10-31 profession.hu's firewall
# blocks requests that claim to be Chrome but do not behave like one.
USER_AGENT = "allasfigyelo/1.0 (+https://github.com/bturnai/n8n-python-job-collector)"


def python_node(name, module, x, y):
    return {"name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y],
            "parameters": {"language": "pythonNative", "pythonCode": sync.build(module)}}


def http_node(name, x, y, accept_header, interval=None):
    batch = {"batchSize": 1}
    if interval:
        batch["batchInterval"] = interval  # be polite to profession.hu
    return {"name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
            "position": [x, y], "onError": "continueRegularOutput",
            "parameters": {
                "url": "={{ $json.url }}", "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "User-Agent", "value": USER_AGENT},
                                                    accept_header]},
                "options": {"batching": {"batch": batch},
                            "response": {"response": {"responseFormat": "text"}},
                            "timeout": 30000}}}


def merge_node(name, x, y, by_position):
    params = ({"mode": "combine", "combineBy": "combineByPosition", "options": {}}
              if by_position else {})  # default mode: append
    return {"name": name, "type": "n8n-nodes-base.merge", "typeVersion": 3.2,
            "position": [x, y], "parameters": params}


def to_text_node(name, x, y, field, filename_expr):
    return {"name": name, "type": "n8n-nodes-base.convertToFile", "typeVersion": 1.1,
            "position": [x, y], "parameters": {
                "operation": "toText", "sourceProperty": field,
                "options": {"encoding": "utf8", "fileName": filename_expr}}}


def write_node(name, x, y, path_expr):
    return {"name": name, "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1.1,
            "position": [x, y], "parameters": {"operation": "write", "fileName": path_expr,
                                               "options": {}}}


def build_workflow(data_dir, wf_id, name, webhook_path, webhook_id, schedule=True,
                   remote_apis=False):
    """remote_apis: also query Remotive, RemoteOK and Arbeitnow. Off since 2026-11-10:
    in two months only one of their postings reached the shortlist."""
    data_dir = data_dir.rstrip("/")
    state_path = f"{data_dir}/allapot/latott.json"
    alert_dir = f"{data_dir}/levelek"
    nodes = [
        {"name": "Kezi inditas", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1,
         "position": [-448, 208], "parameters": {}},
        {"name": "Webhook inditas", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
         "position": [-448, -224], "webhookId": webhook_id,
         "parameters": {"path": webhook_path, "options": {}}},
        # De-duplication state
        {"name": "Latott-lista beolvasasa", "type": "n8n-nodes-base.readWriteFile",
         "typeVersion": 1.1, "position": [-224, 640],
         "parameters": {"fileSelector": state_path, "options": {}}},
        {"name": "Latott-lista JSON", "type": "n8n-nodes-base.extractFromFile", "typeVersion": 1.1,
         "position": [0, 640], "parameters": {"operation": "fromJson", "options": {}}},
        # profession.hu
        python_node("Keresesi URL-ek", "search_urls", 0, 0),
        http_node("Talalati oldalak letoltese", 224, 0,
                  {"name": "Accept-Language", "value": "hu-HU,hu;q=0.9"}, interval=1200),
        merge_node("Oldalak + keresesek", 448, 0, by_position=True),
        merge_node("Oldalak + latott-lista", 672, 0, by_position=False),
        python_node("Uj allasok szurese", "filter_new", 896, 0),
        http_node("Reszletes oldal letoltese", 1120, 0,
                  {"name": "Accept-Language", "value": "hu-HU,hu;q=0.9"}, interval=1200),
        merge_node("Allas + reszletes oldal", 1344, 0, by_position=True),
        python_node("Hirdetes-szoveg kinyerese", "extract_text", 1568, 0),
        python_node("Duplikatumok kiszurese", "dedupe", 2016, 224),
        merge_node("Riport + latott-lista", 2240, 224, by_position=False),
        python_node("Riport osszeallitasa", "report", 2464, 224),
        to_text_node("Szoveggé alakitas", 2688, 0, "markdown", "={{ $json.filename }}"),
        write_node("Riport mentese", 2912, 0,
                   f"={data_dir}/{{{{ $('Riport osszeallitasa').item.json.filename }}}}"),
        to_text_node("JSON alakitas", 2688, 224, "jsonTartalom", "={{ $json.jsonFilename }}"),
        write_node("JSON mentese", 2912, 224,
                   f"={data_dir}/{{{{ $('Riport osszeallitasa').item.json.jsonFilename }}}}"),
        to_text_node("Latott-lista alakitas", 2688, 448, "latottTartalom", "latott.json"),
        write_node("Latott-lista mentese", 2912, 448, state_path),
        # NoFluffJobs and Indeed alert e-mails, saved by the alert-mail workflow
        # (alert_mail.py). An empty folder still lets the run go on: both file
        # nodes always pass on an item, and mail_parse.py skips it.
        {"name": "Ertesito levelek beolvasasa", "type": "n8n-nodes-base.readWriteFile",
         "typeVersion": 1.1, "position": [0, 864], "alwaysOutputData": True,
         "parameters": {"fileSelector": f"{alert_dir}/*.json", "options": {}}},
        {"name": "Ertesito levelek JSON", "type": "n8n-nodes-base.extractFromFile",
         "typeVersion": 1.1, "position": [224, 864], "alwaysOutputData": True,
         "onError": "continueRegularOutput",
         "parameters": {"operation": "fromJson", "options": {}}},
        merge_node("Levelek + latott-lista", 672, 864, by_position=False),
        python_node("Ertesito levelek feldolgozasa", "mail_parse", 896, 864),
        merge_node("Profession + levelek", 1792, 0, by_position=False),
    ]
    if remote_apis:
        nodes += [
            python_node("Remote API URL-ek", "api_urls", 0, 432),
            http_node("Remote API-k letoltese", 224, 432,
                      {"name": "Accept", "value": "application/json"}),
            merge_node("API-k + forrasok", 448, 432, by_position=True),
            merge_node("API-k + latott-lista", 672, 432, by_position=False),
            python_node("API talalatok feldolgozasa", "api_parse", 896, 432),
            merge_node("Forrasok egyesitese", 1792, 224, by_position=False),
        ]
    starts = ["Keresesi URL-ek", "Latott-lista beolvasasa", "Ertesito levelek beolvasasa"] + (["Remote API URL-ek"] if remote_apis else [])
    triggers = ["Kezi inditas", "Webhook inditas"]
    if schedule:
        nodes.insert(0, {"name": "Minden nap 21:30", "type": "n8n-nodes-base.scheduleTrigger",
                         "typeVersion": 1.2, "position": [-448, 0], "parameters": {
                             "rule": {"interval": [{"field": "days", "triggerAtHour": 21,
                                                    "triggerAtMinute": 30}]}}})
        triggers.insert(0, "Minden nap 21:30")
    for index, node in enumerate(nodes):
        node["id"] = f"{wf_id[:8]}-{index:04d}"

    links = [(t, s, 0) for t in triggers for s in starts] + [
        ("Latott-lista beolvasasa", "Latott-lista JSON", 0),
        ("Keresesi URL-ek", "Talalati oldalak letoltese", 0),
        ("Keresesi URL-ek", "Oldalak + keresesek", 0),
        ("Talalati oldalak letoltese", "Oldalak + keresesek", 1),
        ("Latott-lista JSON", "Oldalak + latott-lista", 0),
        ("Oldalak + keresesek", "Oldalak + latott-lista", 1),
        ("Oldalak + latott-lista", "Uj allasok szurese", 0),
        ("Uj allasok szurese", "Reszletes oldal letoltese", 0),
        ("Uj allasok szurese", "Allas + reszletes oldal", 0),
        ("Reszletes oldal letoltese", "Allas + reszletes oldal", 1),
        ("Allas + reszletes oldal", "Hirdetes-szoveg kinyerese", 0),
        ("Latott-lista JSON", "Riport + latott-lista", 0),
        ("Duplikatumok kiszurese", "Riport + latott-lista", 1),
        ("Riport + latott-lista", "Riport osszeallitasa", 0),
        ("Riport osszeallitasa", "Szoveggé alakitas", 0),
        ("Szoveggé alakitas", "Riport mentese", 0),
        ("Riport osszeallitasa", "JSON alakitas", 0),
        ("JSON alakitas", "JSON mentese", 0),
        ("Riport osszeallitasa", "Latott-lista alakitas", 0),
        ("Latott-lista alakitas", "Latott-lista mentese", 0),
        ("Ertesito levelek beolvasasa", "Ertesito levelek JSON", 0),
        ("Latott-lista JSON", "Levelek + latott-lista", 0),
        ("Ertesito levelek JSON", "Levelek + latott-lista", 1),
        ("Levelek + latott-lista", "Ertesito levelek feldolgozasa", 0),
        ("Hirdetes-szoveg kinyerese", "Profession + levelek", 0),
        ("Ertesito levelek feldolgozasa", "Profession + levelek", 1),
    ]
    if remote_apis:
        links += [
            ("Profession + levelek", "Forrasok egyesitese", 0),
            ("Remote API URL-ek", "Remote API-k letoltese", 0),
            ("Remote API URL-ek", "API-k + forrasok", 0),
            ("Remote API-k letoltese", "API-k + forrasok", 1),
            ("Latott-lista JSON", "API-k + latott-lista", 0),
            ("API-k + forrasok", "API-k + latott-lista", 1),
            ("API-k + latott-lista", "API talalatok feldolgozasa", 0),
            ("API talalatok feldolgozasa", "Forrasok egyesitese", 1),
            ("Forrasok egyesitese", "Duplikatumok kiszurese", 0),
        ]
    else:
        links.append(("Profession + levelek", "Duplikatumok kiszurese", 0))
    connections = {}
    for source, target, index in links:
        outputs = connections.setdefault(source, {"main": [[]]})["main"][0]
        outputs.append({"node": target, "type": "main", "index": index})

    return {"id": wf_id, "name": name, "active": False, "nodes": nodes,
            "connections": connections,
            # binaryMode: the published workflow has it; without it the pushed version lost it.
            "settings": {"executionOrder": "v1", "binaryMode": "separate"}}


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="folder of the daily job lists")
    parser.add_argument("--out", required=True)
    parser.add_argument("--id", default="allasfigyelo0001")
    parser.add_argument("--name", default="Allasfigyelo - profession.hu")
    parser.add_argument("--webhook-path", default="allasfigyelo-inditas")
    parser.add_argument("--webhook-id", default="a11a5f19-0000-4000-8000-000000000001")
    parser.add_argument("--no-schedule", action="store_true")
    parser.add_argument("--remote-apis", action="store_true",
                        help="also query Remotive, RemoteOK and Arbeitnow (off since 2026-11-10)")
    args = parser.parse_args(argv)
    workflow = build_workflow(args.data_dir, args.id, args.name, args.webhook_path,
                              args.webhook_id, schedule=not args.no_schedule,
                              remote_apis=args.remote_apis)
    pathlib.Path(args.out).write_text(json.dumps([workflow], ensure_ascii=False, indent=1))
    print(f"{args.out}: {len(workflow['nodes'])} nodes")


if __name__ == "__main__":
    main(sys.argv[1:])
