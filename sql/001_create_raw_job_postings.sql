-- Raw layer: one row per job posting, loaded unchanged from the daily JSON files.
-- Transformations come later (dbt staging/marts); this table is never edited by hand.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.job_postings (
    id            text        PRIMARY KEY,   -- "<source>:<external id>", e.g. remoteok:1137608
    source        text        NOT NULL,      -- profession.hu, arbeitnow, remoteok, remotive
    title         text        NOT NULL,
    company       text,
    location      text,
    place_label   text,                      -- e.g. "Tavmunka/Remote", "Hibrid"
    url           text,
    salary_info   text,
    techs         text,                      -- comma-separated; split in dbt
    description   text,
    collected_on  date        NOT NULL,      -- "datum" of the daily file
    source_file   text        NOT NULL,      -- e.g. allasok_2026-11-01.json
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    payload       jsonb       NOT NULL       -- the original record, unchanged
);
