"""RAG for the scorer: show the model similar postings Bálint has already decided on.

What happens, step by step, for one posting to score:

  1. Find the most similar postings among the hand-labelled TRAIN postings
     (scripts/embed.py: every posting is a list of 384 numbers, and similar
     postings have similar numbers).
  2. Turn each of them into a short text: title, the start of the description,
     and Bálint's decision on it.
  3. Put these texts in front of the posting in the prompt, so the model sees
     how he decided on similar postings before it decides on the new one.

Try it on one posting:   python scripts/rag.py <job_id>
Score with it:           python scripts/llm_score.py score --prompt v5 --rag --run 1 --batch
"""

# How much of each example's description the model sees: all of it, as the collector
# stores at most 2200 characters. With 600, half of the train postings lost their
# requirements section (median start: character 621), and his decisions turn on it
# (seniority, language, student job). Five full examples cost about 5 cents per
# 61 postings x 3 runs on Haiku.
EXAMPLE_CHARS = 2200

# How many examples one posting gets.
K = 5

# Two postings this similar (1.0 = identical) are treated as the same posting.
NEAR_DUPLICATE = 0.99

# The first line of the examples block. It tells the model that the examples only
# show how Bálint decides; the written rules in the system prompt come first.
HEADER = ("Postings similar in topic that he has already decided on. They show how he "
          "decides; the rules above still decide, not these examples.")


def format_example(number, posting, label):
    """One example as three lines of text.

    Example:
        format_example(1, {"title": "Junior Data Analyst", "description": "SQL, Power BI"}, "jelentkeznék")
    returns:
        Example 1, his decision: jelentkeznék
        Title: Junior Data Analyst
        Description: SQL, Power BI
    """
    description= posting["description"]
    
    if description is None:
        description =""
    else: 
        description= description[:EXAMPLE_CHARS]
    return f"Example {number}, his decision: {label}" + "\n" + f"Title: {posting["title"]}" +"\n" + f"Description: {description}"


def format_examples(examples):
    """The whole examples block: the header, then the numbered examples.

    examples: a list of (posting, label) pairs, the most similar posting first.
    The parts are separated by an empty line. No examples: no block, just "".
    """
    if len(examples) == 0:
        return ""

    parts = [HEADER]
    number = 1
    for posting, label in examples:
        parts.append(format_example(number, posting, label))
        number = number + 1

    # "\n\n".join(parts) glues the parts together with an empty line between them.
    return "\n\n".join(parts)


def pick_examples(neighbours, k=K):
    """Choose which neighbours may be shown to the model.

    neighbours: a list of (job_id, similarity) pairs, the most similar first,
                for example [("3038067", 0.968), ("3006727", 0.948), ...]
    k:          keep at most this many.

    A neighbour at or above NEAR_DUPLICATE similarity is practically the same
    posting, so it is always skipped: showing it with Bálint's decision would give
    away the answer. (In the real data "Irodai feladatok - Diákmunka" is in the
    train and the test set twice, with similarity 1.000.) In daily use this loses
    almost nothing: the collector already drops postings re-posted with the same
    company and title.

    Returns the kept job_ids, in the same order.
    """
    ids=[]
    for job_id, similarity in neighbours:
        if similarity< NEAR_DUPLICATE:
            ids.append(job_id)
        
        if(len(ids)== k):
            break
    return ids


def train_candidates(split):
    """The job_ids the examples may come from: only train postings, sorted.

    A test posting shown with his label would give away the answer (the same leak
    as the 96% in the thesis).
    """
    ids=[]
    for job_id, row in split.items():
        if row["split"]=="train":
            ids.append(job_id)
    ids.sort()
    return ids


def examples_for(conn, job_id, split):
    """The examples block for one posting, ready to put into the prompt.

    conn:  the database connection
    split: the rows of eval/split.csv, by job_id, for example
           {"3038067": {"label": "talán", "split": "train"}, ...}
    """
    from embed import nearest
    from llm_score import load_postings

    # Step 1: the postings the examples may come from.
    candidates = train_candidates(split)

    # Step 2: the most similar candidates, from the database. We ask for a few more
    # than K, in case some are skipped as near-duplicates in step 3.
    neighbours = nearest(conn, job_id, candidates, K + 5)

    # Step 3: the ones we show.
    chosen_ids = pick_examples(neighbours, K)

    # Step 4: their title and description from the database, and Bálint's label
    # from split.csv, turned into text.
    postings_by_id = {}
    for posting in load_postings(conn, chosen_ids):
        postings_by_id[posting["id"]] = posting

    examples = []
    for chosen_id in chosen_ids:
        posting = postings_by_id[chosen_id]
        label = split[chosen_id]["label"]
        examples.append((posting, label))
    return format_examples(examples)


def examples_for_all(conn, postings, split):
    """The examples block for every posting to score, by job_id."""
    blocks = {}
    for posting in postings:
        blocks[posting["id"]] = examples_for(conn, posting["id"], split)
    return blocks


def main(argv):
    """Show the examples block for one posting:  python scripts/rag.py <job_id>"""
    from llm_score import connect, read_split

    if len(argv) == 0:
        print(main.__doc__)
        return 2
    job_id = argv[0]
    with connect() as conn:
        print(examples_for(conn, job_id, read_split()))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
