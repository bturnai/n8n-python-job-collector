"""Write a small, readable version of a large fixture file.

The real fixtures are tens of megabytes (mostly downloaded HTML), too big for
an editor. The skeleton keeps the structure but shortens the content:
long strings are cut to STRING_LIMIT characters, and lists keep only their
first LIST_LIMIT elements plus a note of how many there were.

Usage: python scripts/fixture_skeleton.py tests/fixtures/real/<name>.json
       -> writes tests/fixtures/real/<name>_vaz.json next to it
"""
import json
import pathlib
import sys

STRING_LIMIT = 120
LIST_LIMIT = 2


def shorten(value):
    if isinstance(value, str):
        if len(value) <= STRING_LIMIT:
            return value
        return value[:STRING_LIMIT] + f"... [{len(value)} karakter]"
    if isinstance(value, list):
        short = [shorten(element) for element in value[:LIST_LIMIT]]
        if len(value) > LIST_LIMIT:
            short.append(f"... [osszesen {len(value)} elem]")
        return short
    if isinstance(value, dict):
        result = {}
        for key, element in value.items():
            result[key] = shorten(element)
        return result
    return value


def main(path):
    source = pathlib.Path(path)
    target = source.with_name(source.stem + "_vaz.json")
    data = json.loads(source.read_text())
    target.write_text(json.dumps(shorten(data), ensure_ascii=False, indent=2))
    print(f"{target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
