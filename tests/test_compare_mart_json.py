"""The Python copy of the mart's relevance rule (no database needed)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from compare_mart_json import is_relevant


def test_remote_anywhere_is_relevant():
    assert is_relevant({"placeLabel": "Tavmunka/Remote", "location": "Lausanne"})


def test_budapest_area_is_relevant_in_any_work_mode():
    assert is_relevant({"placeLabel": "Barmilyen (helyszini is)", "location": "Pest megye, Budapest"})
    assert is_relevant({"placeLabel": "Hibrid/Home office", "location": "Pest megye"})


def test_hybrid_abroad_is_not_relevant():
    assert not is_relevant({"placeLabel": "Hibrid/Home office", "location": "Svájc"})


def test_missing_location_is_not_budapest():
    assert not is_relevant({"placeLabel": "Barmilyen (helyszini is)", "location": None})
