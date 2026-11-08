-- Repeated runs of the same prompt are kept side by side to measure run-to-run noise.
ALTER TABLE raw.llm_scores ADD COLUMN IF NOT EXISTS run smallint NOT NULL DEFAULT 1;
ALTER TABLE raw.llm_scores DROP CONSTRAINT llm_scores_pkey;
ALTER TABLE raw.llm_scores ADD PRIMARY KEY (job_id, model, prompt_version, effort, run);
