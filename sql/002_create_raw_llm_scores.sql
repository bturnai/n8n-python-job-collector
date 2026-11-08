-- One row per (posting, model, prompt version, effort): the LLM's verdict on whether the
-- posting fits Bálint. Written by scripts/llm_score.py; a rerun of the same combination overwrites.

CREATE TABLE IF NOT EXISTS raw.llm_scores (
    job_id          text        NOT NULL REFERENCES raw.job_postings (id),
    model           text        NOT NULL,   -- e.g. claude-haiku-5-5
    prompt_version  text        NOT NULL,   -- "v1-<sha of system prompt + profile>"
    effort          text        NOT NULL,   -- low / medium / high
    decision        text        NOT NULL CHECK (decision IN ('jelentkeznék', 'talán', 'nem')),
    score           smallint    NOT NULL CHECK (score BETWEEN 1 AND 10),
    pros            jsonb       NOT NULL,   -- list of short reasons for
    cons            jsonb       NOT NULL,   -- list of short reasons against
    missing         jsonb       NOT NULL,   -- must-have requirements he does not meet
    input_tokens    integer,
    output_tokens   integer,
    batch_id        text,                   -- null for synchronous calls
    scored_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, model, prompt_version, effort)
);
