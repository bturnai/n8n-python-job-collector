"""Draw the hand-labelling sample for the LLM scoring eval and write it to Excel.

The labels are Bálint's own decisions (jelentkeznék / talán / nem), so the eval
measures the scorer against him, not against another model. The sample holds
every posting the old Gemini pre-scoring rated 5 or more, a random check of the
ones it rated lower (to see good postings it would have dropped), a random set
of the unscored postings since 2026-10-16, and always the postings the evening
review e-mailed or he applied to. The old scores are not shown in the sheet, so
they cannot sway the labels.

The sheet is made for fast reading: seniority, experience, language and tools
get their own columns, and the one-line description is cut into bullets under
its own headings (tasks, requirements, nice to have). All of it is rule-based
on purpose: a model-written summary would put a model's reading into the labels
that the model is later measured against.

Usage:
  python scripts/make_label_sample.py OUT.xlsx [--seed 42]
"""
import argparse
import json
import os
import pathlib
import random
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT.parent / "allasfigyelo"
APPLICATION_LOG = ROOT.parent / "dokumentumok" / "Allaskeresesi_naplo.xlsx"

LABELS = ["jelentkeznék", "talán", "nem"]
# How many postings each old score band gives; None = all of them.
QUOTAS = {"5+": None, "below 5": 15, "unscored": 10}

UPPER, LOWER = "A-ZÁÉÍÓÖŐÚÜŰ", "a-záéíóöőúüűäß"
COMPANY_SUFFIX = re.compile(r"\b(kft|zrt|nyrt|bt|ltd|gmbh|ag|inc|llc)\b\.?")

# Heading in the description -> the column its bullets go to.
SECTIONS = {
    "tasks": r"Feladatok|What you(?:'|’)ll do|What you will do|Your role|The role|"
             r"Key responsibilities|Your responsibilities|Responsibilities|Your tasks|Tasks|"
             r"Deine Aufgaben|Ihre Aufgaben",
    "requirements": r"Elvárások|Feltételek|What you bring|Requirements|Qualifications|Your profile|"
                    r"Who you are|What we(?:'|’)re looking for|Must[- ]have|Dein Profil|Ihr Profil",
    "nice": r"Előnyt jelent|Előny|Nice[- ]to[- ]have|Bonus",
    "other": r"Amit kínálunk|Ajánlatunk|What we offer|Benefits|Wir bieten|About the role|Állás leírása",
}
SECTION_HEADING = re.compile("|".join(f"(?P<{name}>\\b(?:{pat}))\\b:?"
                                      for name, pat in SECTIONS.items()))

# Capitalised words that are names inside a sentence, not the start of a new item.
NAMES = {"Python", "Git", "Docker", "Linux", "Excel", "Power", "Tableau", "Java", "Azure",
         "Google", "Microsoft", "Spark", "Databricks", "Snowflake", "Kubernetes", "Airflow",
         "Kafka", "Pandas", "Polars", "Scala", "Oracle", "Jira", "Confluence", "Office",
         "Cloud", "Platform", "Budapest", "Magyarország", "Hungary", "Europe", "European",
         "Apache", "Iceberg", "Business", "Intelligence", "Data", "Machine", "Learning",
         "Science", "Looker", "Qlik", "Synapse", "Fabric", "Hugging", "Face", "Named", "Entity",
         "TensorFlow", "PyTorch", "Keras", "Transformerek", "Flask", "FastAPI", "Django"}
SENIORITY = [("senior", r"\bsenior\b|\blead\b|\bprincipal\b|\bstaff\b|\bhead of\b|vezető"),
             ("junior", r"\bjunior\b|\bjr\b|gyakornok|\bintern|trainee|pályakezdő|graduate"),
             ("medior", r"\bmedior\b|\bmid\b")]


def normalize(text):
    """Lower case, no legal-form suffix or punctuation: 'MOL Nyrt.' -> 'mol'."""
    text = COMPANY_SUFFIX.sub("", (text or "").lower())
    return re.sub(r"[^\w]+", " ", text).strip()


def band(score):
    """The old Gemini score band; postings since 2026-10-16 have no score."""
    if score is None:
        return "unscored"
    return "5+" if score >= 5 else "below 5"


def pick_sample(postings, must_ids, quotas, seed):
    """must_ids, then per band its quota (None = all) drawn at random; shuffled."""
    rng = random.Random(seed)
    chosen = [p for p in postings if p["id"] in must_ids]
    for name, quota in quotas.items():
        group = [p for p in postings if band(p["score"]) == name and p["id"] not in must_ids]
        rng.shuffle(group)
        chosen += group if quota is None else group[:quota]
    rng.shuffle(chosen)
    return chosen


def is_german(text):
    return len(re.findall(r"\b(und|wir|die|der|für|mit|Sie)\b", text or "")) >= 5


def is_hungarian(text):
    """English and German postings end their sentences; Hungarian lists often do not."""
    english = len(re.findall(r"\b(the|and|you|with|of|to)\b", text or "")) >= 5
    return not english and not is_german(text)


def _is_name(word):
    core = word.strip(".,;:()/")
    return len(core) < 2 or bool(re.search(f"[{UPPER}].*[{UPPER}]", core)) or core in NAMES


def bullets(text, hungarian=True):
    """Cut a run-together list into items.

    Bullets and semicolons the employer wrote always start a new item. Beyond
    that, the collector joined list items with a space, so in a Hungarian list a
    new item shows up as a capitalised word right after a lower-case one
    ("...fejlesztése Mesterséges..."). English and German postings end their
    sentences (and German capitalises every noun), so there only sentence ends count.
    """
    items = []
    for piece in re.split(r"\s*[•;]\s*", text):
        items += _split_piece(piece, hungarian) if piece.strip() else []
    return items


def _split_piece(text, hungarian):
    words, items, current = text.split(), [], []
    for i, word in enumerate(words):
        prev = words[i - 1] if i else ""
        capital = bool(re.match(f"[{UPPER}]", word))
        new_item = capital and prev.endswith((".", "!", "?", ":"))
        if capital and hungarian and prev and not _is_name(word) and not _is_name(prev) \
                and not re.match(f"[{UPPER}]", prev):
            new_item = new_item or bool(re.search(f"[{LOWER}0-9)]$", prev))
        if new_item and current:
            items.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        items.append(" ".join(current))
    merged = []
    for item in items:  # a guessed one- or two-word piece is almost always a broken name
        if merged and len(item.split()) < 3:
            merged[-1] += " " + item
        else:
            merged.append(item)
    return merged


def split_sections(text):
    """{column: text} from the headings in the description; text before any heading is 'other'."""
    parts, column, start = {}, "other", 0
    for match in SECTION_HEADING.finditer(text or ""):
        parts[column] = parts.get(column, "") + " " + text[start:match.start()]
        column, start = match.lastgroup, match.end()
    parts[column] = parts.get(column, "") + " " + (text or "")[start:]
    return {name: body.strip() for name, body in parts.items() if body.strip()}


def as_bullets(text, hungarian):
    return "\n".join("• " + item for item in bullets(text, hungarian)) if text else ""


def tools(techs):
    """profession.hu: the 'Elvárt technológiák' list; other sources: their tag list."""
    if not techs:
        return ""
    match = re.match(r"Elvárt technológiák (.*?) (?:Biztosított eszközök|Elvárások)", techs)
    return match.group(1) if match else ("" if "Elvárások" in techs else techs)


def experience(techs, text):
    for pattern in (r"\d+-\d+ év tapasztalat|Nem kell tapasztalat|\d+ év (?:feletti|alatti) tapasztalat",):
        match = re.search(pattern, techs or "")
        if match:
            return match.group(0)
    match = re.search(r"(?:legalább |at least |min(?:imum)?\.? )?\d+\+?(?:\s*-\s*\d+)?\s*"
                      r"(?:év|years?|Jahre)", text or "", re.I)
    return f"{match.group(0)} (szövegből)" if match else ""


def language(techs, text):
    tags = re.findall(r"(?:Angol|Német|Magyar) \w+", (techs or "").split("Elvárások")[-1]
                      if techs and "Elvárások" in techs else "")
    found = list(dict.fromkeys(tags))
    if is_german(text):
        found.append("a hirdetés németül")
    elif re.search(r"\b(német|German|Deutsch)\b", text or ""):
        found.append("német említve")
    return ", ".join(found)


def seniority(title):
    for level, pattern in SENIORITY:
        if re.search(pattern, title or "", re.I):
            return level
    return ""


def emailed_ids():
    sent = json.loads((DATA_DIR / "elkuldve.json").read_text(encoding="utf-8"))
    return {str(item["id"]) for item in sent["elkuldott_allasok"]}


def applied_ids(postings):
    """Postings whose company and title match a row of the application log."""
    import openpyxl

    sheet = openpyxl.load_workbook(APPLICATION_LOG, read_only=True)["Munka1"]
    applied = {(normalize(row[2]), normalize(row[1]))
               for row in sheet.iter_rows(min_row=3, values_only=True) if row[1] and row[2]}
    return {p["id"] for p in postings
            if (normalize(p["company"]), normalize(p["title"])) in applied}


def load_postings():
    import psycopg

    query = """select id, collected_on, source, title, company, location, place_label,
                      url, techs, description, (payload->>'score')::int
               from raw.job_postings"""
    with psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs")) as conn:
        rows = conn.execute(query).fetchall()
    keys = ["id", "collected_on", "source", "title", "company", "location",
            "place_label", "url", "techs", "description", "score"]
    return [dict(zip(keys, row)) for row in rows]


COLUMNS = [  # header, width
    ("döntés", 14), ("megjegyzés", 26), ("cím", 30), ("cég", 22), ("helyszín", 18),
    ("munkarend", 16), ("szint", 9), ("tapasztalat", 16), ("nyelv", 18), ("eszközök", 26),
    ("feladatok", 55), ("elvárások", 55), ("előny", 40), ("egyéb szöveg", 45),
    ("link", 24), ("job_id", 12), ("gyűjtve", 11),
]


def sheet_row(p):
    text = p["description"] or ""
    hungarian = is_hungarian(text)
    parts = split_sections(text)
    return ["", "", p["title"], p["company"], p["location"], p["place_label"],
            seniority(p["title"]), experience(p["techs"], text), language(p["techs"], text),
            tools(p["techs"]),
            as_bullets(parts.get("tasks"), hungarian),
            as_bullets(parts.get("requirements"), hungarian),
            as_bullets(parts.get("nice"), hungarian), as_bullets(parts.get("other"), hungarian),
            p["url"], p["id"], p["collected_on"]]


def write_sheet(sample, path):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "címkék"
    ws.append([header for header, _ in COLUMNS])
    for p in sample:
        ws.append(sheet_row(p))
    choice = DataValidation(type="list", formula1='"' + ",".join(LABELS) + '"',
                            allow_blank=True)
    ws.add_data_validation(choice)
    choice.add(f"A2:A{len(sample) + 1}")
    for i, (_, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDE7F3")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    postings = load_postings()
    ids = {p["id"] for p in postings}
    emailed, applied = emailed_ids() & ids, applied_ids(postings)
    sample = pick_sample(postings, emailed | applied, QUOTAS, args.seed)
    write_sheet(sample, args.out)
    counts = {}
    for p in sample:
        counts[band(p["score"])] = counts.get(band(p["score"]), 0) + 1
    print(f"{len(sample)} postings -> {args.out}")
    print(f"  e-mailed: {len(emailed)}, applied: {len(applied)}, overlap: {len(emailed & applied)}")
    print(f"  by old score band: {dict(sorted(counts.items()))}")


if __name__ == "__main__":
    main()
