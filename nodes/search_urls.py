"""Node "Keresesi URL-ek": builds the profession.hu search-result URLs.

The last URL position is the work-location filter: 6 = remote, 5 = hybrid,
no code = any location (on-site jobs included).
"""

ZERO_FILLER = ",".join(["0"] * 32)

KEYWORDS = [
    "data",
    "analyst",
    "elemzo",  # without accents: 'adatelemzo' falls back to a generic list
    "python",
    "machine-learning",
    "deep-learning",
    "junior",
    "data-scientist",
    "adattudos",
    "scikit-learn",
]
# Multi-word keywords need a HYPHEN (data-analyst). A space (%20 or +) and most
# accented words silently fall back to a generic list: it looks like it works,
# but returns the wrong data. Check that a new keyword really changes the results.

FILTERS = [
    {"code": 6, "label": "Tavmunka/Remote", "pages": 3},
    {"code": 5, "label": "Hibrid/Home office", "pages": 2},
    {"code": 0, "label": "Barmilyen (helyszini is)", "pages": 3},
]


def main(items):
    out = []
    for keyword in KEYWORDS:
        for flt in FILTERS:
            for page in range(1, flt["pages"] + 1):
                url = f"https://www.profession.hu/allasok/{page},0,0,{keyword},{ZERO_FILLER}"
                if flt["code"]:
                    url += f",{flt['code']}"
                out.append({"json": {
                    "url": url, "keyword": keyword,
                    "placeLabel": flt["label"], "page": page,
                }})
    return out
