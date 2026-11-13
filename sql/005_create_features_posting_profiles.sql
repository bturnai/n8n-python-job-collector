-- A short profile of each posting, extracted by Claude: seniority, years of experience,
-- languages, requirements, tasks. Computed from raw.job_postings, so it lives in the
-- features schema, next to the embeddings; the raw text is never changed by it.
-- The embedding of this profile is closer to his decision than the embedding of the
-- whole text, which mostly captures the topic (see README, RAG section).

CREATE TABLE IF NOT EXISTS features.posting_profiles (
    job_id       text        PRIMARY KEY REFERENCES raw.job_postings (id),
    model        text        NOT NULL,   -- the Claude model that extracted it
    profile      jsonb       NOT NULL,   -- seniority, years_experience, languages, ...
    dropped      integer     NOT NULL,   -- items dropped because the posting does not contain them
    text_sha     text        NOT NULL,   -- hash of the posting text; a changed posting is redone
    created_at   timestamptz NOT NULL DEFAULT now()
);
