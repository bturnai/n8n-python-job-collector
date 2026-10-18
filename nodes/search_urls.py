"""Node "Keresesi URL-ek": builds the profession.hu search-result URLs.

One URL per keyword, location filter and result page:
10 keywords x (3 + 2 + 3 pages) = 80 URLs.

A search URL looks like this (32 zeros in the middle, shortened here):
    https://www.profession.hu/allasok/2,0,0,python,0,0,...,0,6
                                      |      |              |
                                    page  keyword   location filter
"""

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

# The last number of the URL filters by work location. Code 0 means "no filter",
# and then the number is left out of the URL completely.
LOCATION_FILTERS = [
    {"code": 6, "label": "Tavmunka/Remote", "pages": 3},
    {"code": 5, "label": "Hibrid/Home office", "pages": 2},
    {"code": 0, "label": "Barmilyen (helyszini is)", "pages": 3},
]

# The search URL has 32 unused positions; profession.hu expects them as zeros.
UNUSED_POSITIONS = ",".join(["0"] * 32)


def build_search_url(page, keyword, location_code):
    """Example: build_search_url(2, "python", 6) -> ".../allasok/2,0,0,python,0,...,0,6" """
    url = f"https://www.profession.hu/allasok/{page},0,0,{keyword},{UNUSED_POSITIONS}"
    if location_code != 0:
        url = url + "," + str(location_code)
    return url


def main(items):
    search_items = []
    for keyword in KEYWORDS:
        for location in LOCATION_FILTERS:
            for page in range(1, location["pages"] + 1):
                search_items.append({"json": {
                    "url": build_search_url(page, keyword, location["code"]),
                    "keyword": keyword,
                    "placeLabel": location["label"],
                    "page": page,
                }})
    return search_items
