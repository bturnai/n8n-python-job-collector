"""Download again the profession.hu postings whose text was cut at 2200 characters.

Until 2026-11-13 the collector kept only the first 2200 characters of each posting,
and a quarter of the postings lost part of their requirements. Postings still online
can be downloaded again and read with the new collector code (nodes/extract_text.py).

The stored text is replaced only when it is the start of the new text: then it is the
same posting, and the new text only adds what was cut. If the posting was edited or
taken down, the stored text stays.

    python scripts/refetch_texts.py            # one request per second, about 8 minutes
"""
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "nodes"))
from llm_score import connect  # noqa: E402
import extract_text  # noqa: E402

USER_AGENT = "allasfigyelo/1.0 (+https://github.com/bturnai/n8n-python-job-collector)"
CUT_LENGTH = 2190      # texts this long or longer were cut by the old collector
PAUSE_SECONDS = 1      # be gentle with the site


def is_longer_version(old_text, new_text):
    """True if new_text is the same posting as old_text, only longer.

    The old collector cut at 2200 UTF-16 units, which can split an emoji; the loader
    then replaced the broken last character. So the last 2 characters are not compared.

    Example: is_longer_version("Feladatok: SQL, Pyt", "Feladatok: SQL, Python, Excel") -> True
    """
    if len(new_text) <= len(old_text):
        return False
    return new_text.startswith(old_text[:-2])


def download_text(url):
    """The posting text of a job page, read the same way as the daily collector reads it."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    html = urllib.request.urlopen(request, timeout=20).read().decode("utf-8", "replace")
    item = {"json": {"id": "refetch", "data": html}}
    return extract_text.main([item])[0]["json"]["description"]


def main():
    with connect() as conn:
        rows = conn.execute(
            """select id, payload->>'url', description from raw.job_postings
               where source = 'profession.hu' and length(description) >= %s
               order by collected_on desc""", (CUT_LENGTH,)).fetchall()
        print(f"{len(rows)} cut postings to try", flush=True)

        replaced = 0
        unchanged = 0
        failed = 0
        for job_id, url, old_text in rows:
            try:
                new_text = download_text(url)
            except Exception:              # taken down, timeout, network error
                failed += 1
                time.sleep(PAUSE_SECONDS)
                continue

            if is_longer_version(old_text, new_text):
                conn.execute("update raw.job_postings set description = %s where id = %s",
                             (new_text, job_id))
                conn.commit()
                replaced += 1
            else:
                unchanged += 1             # edited, taken down (an empty page), or not longer
            time.sleep(PAUSE_SECONDS)

        print(f"replaced: {replaced} | kept (not the same text or not longer): {unchanged} "
              f"| could not download: {failed}")


if __name__ == "__main__":
    main()
