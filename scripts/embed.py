"""Embed postings with a local multilingual model and find similar ones in PostgreSQL (pgvector).

    python scripts/embed.py embed                        # embed new or changed postings
    python scripts/embed.py embed --profiles             # embed the Claude profiles instead
    python scripts/embed.py neighbors <job_id> --k 5     # the most similar labelled train postings

The text is the title plus the description, without the company name.
"""
import argparse
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from llm_score import connect, read_split  # noqa: E402

MODEL = "intfloat/multilingual-e5-small"
MAX_TOKENS = 512
# e5 models were trained with a prefix; "query: " on both sides is the one for comparing
# texts of the same kind (posting with posting), "passage: " is for documents searched by a question.
PREFIX = "query: "
# The embeddings of the Claude profiles (scripts/posting_profile.py) are stored next to
# the full-text ones, under this name in the model column.
PROFILE_KEY = MODEL + ":profile"


def embedding_text(title, description):
    return f"{PREFIX}{title}\n\n{description or ''}".strip()


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def texts_to_embed(conn, profiles):
    """(job_id, text) for every posting: the full text, or with profiles=True the profile."""
    texts = []
    if profiles:
        from posting_profile import profile_text
        rows = conn.execute("""select p.job_id, j.title, p.profile from features.posting_profiles p
                               join raw.job_postings j on j.id = p.job_id""").fetchall()
        for job_id, title, profile in rows:
            texts.append((job_id, PREFIX + profile_text(title, profile)))
    else:
        for job_id, title, description in conn.execute(
                "select id, title, description from raw.job_postings").fetchall():
            texts.append((job_id, embedding_text(title, description)))
    return texts


def cmd_embed(args):
    from pgvector.psycopg import register_vector
    from sentence_transformers import SentenceTransformer

    key = PROFILE_KEY if args.profiles else MODEL
    with connect() as conn:
        register_vector(conn)
        rows = texts_to_embed(conn, args.profiles)
        done = dict(conn.execute("select job_id, text_sha from features.job_embeddings where model = %s",
                                 (key,)).fetchall())
        todo = []
        for job_id, text in rows:
            if done.get(job_id) != text_sha(text):
                todo.append((job_id, text))
        print(f"{len(rows)} texts, {len(todo)} to embed as {key}", flush=True)
        if not todo:
            return
        model = SentenceTransformer(MODEL)
        texts = [t for _, t in todo]
        lengths = [len(ids) for ids in model.tokenizer(texts)["input_ids"]]
        vectors = model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=True)
        for (job_id, text), n_tokens, vector in zip(todo, lengths, vectors):
            conn.execute(
                """
                insert into
                    features.job_embeddings 
                    (
                        job_id,
                        model,
                        embedding,
                        text_sha,
                        truncated)
                values (%s, %s, %s, %s, %s)
                on conflict 
                    (job_id, model) do update set embedding = excluded.embedding,
                    text_sha = excluded.text_sha, truncated = excluded.truncated, embedded_at = now()""",
                (job_id, key, vector, text_sha(text), n_tokens > MAX_TOKENS))
        conn.commit()
        truncated = sum(n > MAX_TOKENS for n in lengths)
        print(f"stored {len(todo)}; {truncated} longer than {MAX_TOKENS} tokens (the model reads the start only)")


def nearest(conn, job_id, candidate_ids, k, key=MODEL):
    """The k candidates closest to job_id by cosine distance; job_id itself is never returned.

    key: which embeddings to compare, MODEL (full text) or PROFILE_KEY (Claude profiles).
    """
    return conn.execute(
        """
        select 
            e.job_id,
            1 - (e.embedding <=> q.embedding) as similarity
        from 
            features.job_embeddings e
        join
            features.job_embeddings q 
        on 
            q.job_id = %s and q.model = e.model
        where 
            e.model = %s and
            e.job_id = any(%s)
            and e.job_id <> %s
        order by
            e.embedding <=> q.embedding
        limit 
            %s
        """,
        (job_id, key, list(candidate_ids), job_id, k)).fetchall()


def cmd_neighbors(args):
    split = read_split()
    train = [i for i, r in split.items() if r["split"] == "train"]
    with connect() as conn:
        title = dict(conn.execute("select id, title from raw.job_postings").fetchall())
        own = split.get(args.job_id)
        print(f"{args.job_id}: {title[args.job_id]}"
              + (f"  [your label: {own['label']}, {own['split']}]" if own else "  [not labelled]"))
        for job_id, similarity in nearest(conn, args.job_id, train, args.k):
            print(f"  {similarity:.3f}  {split[job_id]['label']:<13} {title[job_id]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_embed = sub.add_parser("embed")
    p_embed.add_argument("--profiles", action="store_true", help="embed the Claude profiles")
    p_nb = sub.add_parser("neighbors")
    p_nb.add_argument("job_id")
    p_nb.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    {"embed": cmd_embed, "neighbors": cmd_neighbors}[args.cmd](args)


if __name__ == "__main__":
    main()
