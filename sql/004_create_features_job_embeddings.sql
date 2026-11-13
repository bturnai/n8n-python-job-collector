-- Embeddings of the postings, for similarity search (RAG).
-- Not in the raw layer: raw holds source data unchanged, this is computed from it.
-- One row per (posting, embedding model), so two models can be compared side by side.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS features;

CREATE TABLE IF NOT EXISTS features.job_embeddings (
    job_id       text        NOT NULL REFERENCES raw.job_postings (id),
    model        text        NOT NULL,   -- e.g. intfloat/multilingual-e5-small
    embedding    vector(384) NOT NULL,   -- unit length, so cosine distance is 1 - dot product
    text_sha     text        NOT NULL,   -- hash of the embedded text; a changed posting is re-embedded
    truncated    boolean     NOT NULL,   -- the text was longer than the model reads (512 tokens)
    embedded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, model)
);
