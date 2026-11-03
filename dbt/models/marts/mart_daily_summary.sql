-- One row per collection day: how many postings came in and how many matched.

select
    collected_on,
    count(*)                                              as postings,
    count(*) filter (where work_mode = 'remote' or is_budapest_area) as relevant,
    count(*) filter (where work_mode = 'remote')          as remote,
    count(*) filter (where work_mode = 'hybrid')          as hybrid,
    count(*) filter (where is_budapest_area)              as budapest_area

from {{ ref('stg_job_postings') }}

group by collected_on
