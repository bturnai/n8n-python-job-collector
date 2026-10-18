"""Node "Remote API URL-ek": international remote job APIs (no API key needed).

Remotive's search is imprecise, so it is queried broadly and filtered locally.
"""

REMOTIVE_QUERIES = ["data", "data analyst", "data scientist", "machine learning"]

# Characters that may appear in a URL as they are. Everything else is
# percent-encoded, e.g. a space becomes "%20".
SAFE_URL_CHARACTERS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")


def encode_uri_component(text):
    """Make text safe to put into a URL, like JavaScript's encodeURIComponent.

    Python's urllib would do this, but the n8n sandbox does not allow it.
    Example: encode_uri_component("data analyst") -> "data%20analyst"
    """
    encoded = ""
    for character in text:
        if character in SAFE_URL_CHARACTERS:
            encoded += character
        else:
            # A character can take several bytes in UTF-8 ("é" is 2 bytes);
            # each byte is written as % and two hex digits: "é" -> "%C3%A9".
            for byte in character.encode("utf-8"):
                encoded += f"%{byte:02X}"
    return encoded


def main(items):
    api_items = []

    for query in REMOTIVE_QUERIES:
        url = ("https://remotive.com/api/remote-jobs?search="
            + encode_uri_component(query) + "&limit=40")
        api_items.append({"json": {"forras": "remotive", "url": url}})

    api_items.append({"json": {"forras": "remoteok", "url": "https://remoteok.com/api"}})
    api_items.append({"json": {"forras": "arbeitnow",
                            "url": "https://www.arbeitnow.com/api/job-board-api"}})
    return api_items
