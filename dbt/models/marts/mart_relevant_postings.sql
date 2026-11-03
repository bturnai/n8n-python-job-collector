-- Postings that match the search: fully remote, or hybrid / on-site in the
-- Budapest area. One row per posting, with the text the evening review reads.

select
    collected_on,
    job_id,
    title,
    company,
    work_mode,
    location,
    source,
    url,
    techs_raw,
    description

from {{ ref('stg_job_postings') }}

where work_mode = 'remote'
   or is_budapest_area
