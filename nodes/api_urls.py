"""Node "Remote API URL-ek": international remote job APIs (no API key needed).

Remotive's search is imprecise, so it is queried broadly and filtered locally.
"""

REMOTIVE_QUERIES = ["data", "data analyst", "data engineer", "machine learning"]
UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")


def encode_uri_component(text):
    # urllib is not on the sandbox's module allow-list.
    return "".join(
        ch if ch in UNRESERVED else "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
        for ch in text
    )


def main(items):
    out = [
        {"json": {"forras": "remotive",
                  "url": f"https://remotive.com/api/remote-jobs?search={encode_uri_component(q)}&limit=40"}}
        for q in REMOTIVE_QUERIES
    ]
    out.append({"json": {"forras": "remoteok", "url": "https://remoteok.com/api"}})
    out.append({"json": {"forras": "arbeitnow", "url": "https://www.arbeitnow.com/api/job-board-api"}})
    return out
