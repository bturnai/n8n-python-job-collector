"""Compare stored LLM verdicts and the old Gemini scores with Bálint's hand labels.

    python scripts/llm_eval.py              # train split
    python scripts/llm_eval.py --split test # only once the prompt is final

Each prompt version may have several runs; the summary line shows the mean and range
across runs, how many verdicts flip between runs, and the majority vote of the runs.

The Gemini baseline only had a 1-10 score, so its thresholds for the three decisions
are fitted on the train split and then reused unchanged on test.
"""
import argparse
import csv
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPLIT_FILE = ROOT / "eval" / "split.csv"
DECISIONS = ["jelentkeznék", "talán", "nem"]
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}  # $ per 1M in/out tokens


def metrics(pairs):
    """pairs: [(label, predicted)]. Returns the confusion matrix and the numbers that matter."""
    confusion = {(l, p): 0 for l in DECISIONS for p in DECISIONS}
    for label, predicted in pairs:
        confusion[(label, predicted)] += 1
    yes = sum(confusion[("jelentkeznék", p)] for p in DECISIONS)
    return {
        "n": len(pairs),
        "accuracy": sum(confusion[(d, d)] for d in DECISIONS) / len(pairs) if pairs else 0.0,
        "yes_recall": confusion[("jelentkeznék", "jelentkeznék")] / yes if yes else 0.0,
        "yes_missed": confusion[("jelentkeznék", "nem")],
        "confusion": confusion,
    }


def to_decision(score, high, low):
    return "jelentkeznék" if score >= high else "talán" if score >= low else "nem"


def fit_thresholds(pairs):
    """pairs: [(label, gemini score)]. Thresholds with the best accuracy; ties go to higher recall."""
    best = None
    for high in range(2, 11):
        for low in range(1, high + 1):
            m = metrics([(l, to_decision(s, high, low)) for l, s in pairs])
            key = (m["accuracy"], m["yes_recall"])
            if best is None or key > best[0]:
                best = (key, high, low)
    return best[1], best[2]


def majority(decisions):
    """Most frequent decision; a tie goes to the more hopeful one (missing a good job is the costly error)."""
    return max(DECISIONS, key=lambda d: (decisions.count(d), -DECISIONS.index(d)))


def print_block(title, m, extra=""):
    print(f"\n{title}  (n={m['n']}){extra}")
    print(f"  egyezés {m['accuracy']:.0%} | jelentkeznék-felidézés {m['yes_recall']:.0%} "
          f"| jelentkeznék, de 'nem'-nek mondta: {m['yes_missed']}")
    print("  te \\ modell     " + "".join(f"{d:>14}" for d in DECISIONS))
    for label in DECISIONS:
        print(f"  {label:15}" + "".join(f"{m['confusion'][(label, p)]:>14}" for p in DECISIONS))


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="train", choices=["train", "test", "all"])
    args = parser.parse_args()

    with open(SPLIT_FILE, newline="", encoding="utf-8") as f:
        split = {r["job_id"]: r for r in csv.DictReader(f)}
    labels = {i: r["label"] for i, r in split.items() if args.split == "all" or r["split"] == args.split}
    train = [(r["label"], i) for i, r in split.items() if r["split"] == "train"]

    with psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs")) as conn:
        gemini = dict(conn.execute(
            "select id, (payload->>'score')::int from raw.job_postings where payload ? 'score'").fetchall())
        runs = conn.execute(
            """select model, prompt_version, effort, run, job_id, decision, input_tokens, output_tokens
               from raw.llm_scores where job_id = any(%s)
               order by model, prompt_version, effort, run""", (list(labels),)).fetchall()

    high, low = fit_thresholds([(l, gemini[i]) for l, i in train if gemini.get(i) is not None])
    scored = [(labels[i], to_decision(gemini[i], high, low)) for i in labels if gemini.get(i) is not None]
    print_block("Gemini (régi)", metrics(scored),
                f"; küszöb: {high}+ jelentkeznék, {low}-{high - 1} talán; pontozatlan: {len(labels) - len(scored)}")

    grouped = {}
    for model, version, effort, run, job_id, decision, tin, tout in runs:
        grouped.setdefault((model, version, effort), {}).setdefault(run, []).append(
            (job_id, decision, tin or 0, tout or 0))
    for (model, version, effort), by_run in grouped.items():
        price_in, price_out = PRICES.get(model, (0, 0))
        per_run = []
        for run, rows in by_run.items():
            m = metrics([(labels[j], d) for j, d, _, _ in rows])
            tin, tout = sum(r[2] for r in rows), sum(r[3] for r in rows)
            cost = (tin * price_in + tout * price_out) / 1e6
            print_block(f"{model} {version} {effort} futás {run}", m,
                        f"; {tin} + {tout} token, listaáron ${cost:.3f} (batch: fele)")
            per_run.append(m)
        if len(by_run) < 2:
            continue
        votes = {}
        for rows in by_run.values():
            for j, d, _, _ in rows:
                votes.setdefault(j, []).append(d)
        complete = {j: v for j, v in votes.items() if len(v) == len(by_run)}
        flipping = sum(len(set(v)) > 1 for v in complete.values())
        accs = [m["accuracy"] for m in per_run]
        recalls = [m["yes_recall"] for m in per_run]
        print(f"\n== {model} {version} {effort}: {len(by_run)} futás ==")
        print(f"  egyezés átlag {sum(accs) / len(accs):.0%} (sáv {min(accs):.0%}-{max(accs):.0%}) | "
              f"felidézés átlag {sum(recalls) / len(recalls):.0%} (sáv {min(recalls):.0%}-{max(recalls):.0%})")
        print(f"  futásonként változó döntés: {flipping} / {len(complete)} hirdetés")
        print_block(f"{model} {version} {effort} többségi szavazat",
                    metrics([(labels[j], majority(v)) for j, v in complete.items()]))

if __name__ == "__main__":
    main()
