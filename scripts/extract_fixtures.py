"""Extract real node inputs/outputs from stored n8n executions as test fixtures.

n8n keeps the last executions in ~/.n8n/database.sqlite, serialized with the
`flatted` format. This script revives them and writes, for every Code node of
interest, the items it received and the items it returned. The parity tests
compare the Python ports against these recorded JavaScript outputs.

The fixtures contain scraped listings and e-mails, so they are git-ignored.

Usage: python scripts/extract_fixtures.py <execution_id> [<execution_id> ...]
"""
import json
import pathlib
import sqlite3
import sys

DB = pathlib.Path.home() / ".n8n" / "database.sqlite"
OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "real"


def flatted_parse(text):
    """Minimal reader for the `flatted` JSON encoding used by n8n."""
    table = json.loads(text)
    revived = [False] * len(table)

    def revive(index):
        value = table[index]
        if isinstance(value, (dict, list)) and not revived[index]:
            revived[index] = True
            keys = list(value.keys()) if isinstance(value, dict) else range(len(value))
            for key in keys:
                if isinstance(value[key], str):
                    value[key] = revive(int(value[key]))
        return value

    return revive(0)


def node_items(run_data, name):
    runs = run_data.get(name) or []
    if not runs:
        return None
    main = (runs[0].get("data") or {}).get("main") or [[]]
    return [{"json": item.get("json", {})} for item in (main[0] or [])]


def main(execution_ids):
    con = sqlite3.connect(DB)
    OUT.mkdir(parents=True, exist_ok=True)
    for exec_id in execution_ids:
        wf_id, raw, nodes = con.execute(
            "select e.workflowId, d.data, d.workflowData from execution_entity e "
            "join execution_data d on d.executionId = e.id where e.id = ?",
            (exec_id,),
        ).fetchone()
        run_data = flatted_parse(raw)["resultData"]["runData"]
        workflow = json.loads(nodes)
        parents = {}
        for src, outputs in workflow["connections"].items():
            for branch in outputs.get("main", []):
                for conn in branch or []:
                    parents.setdefault(conn["node"], []).append(src)
        result = {"execution": exec_id, "workflow": wf_id, "nodes": {}}
        for node in workflow["nodes"]:
            if node["type"] != "n8n-nodes-base.code" or node.get("disabled"):
                continue
            name = node["name"]
            output = node_items(run_data, name)
            if output is None:
                continue
            inputs = []
            for parent in parents.get(name, []):
                inputs.extend(node_items(run_data, parent) or [])
            result["nodes"][name] = {"input": inputs, "output": output}
        # Outputs of every node, so that `$('Node')` references can be rebuilt.
        result["all_outputs"] = {
            name: node_items(run_data, name) for name in run_data
        }
        target = OUT / f"{wf_id}_{exec_id}.json"
        target.write_text(json.dumps(result, ensure_ascii=False))
        print(target.name, "->", ", ".join(result["nodes"]))


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]])
