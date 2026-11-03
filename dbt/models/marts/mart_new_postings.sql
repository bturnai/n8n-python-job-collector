-- The newest collection day's postings that fit the search: remote anywhere,
-- or any work mode in the Budapest area (CLAUDE.md, section 5).
-- "Newest day" instead of today, so the table is right whenever it is built.

with postings as (

    select * from {{ ref('stg_job_postings') }}

),

latest_day as (

    select max(collected_on) as collected_on from postings

)

select
    p.collected_on,
    p.job_id,
    p.source,
    p.title,
    p.company,
    p.location,
    p.work_mode,
    p.has_salary,
    p.salary_info,
    p.url,
    p.techs_raw,
    p.description
from postings p
join latest_day d on p.collected_on = d.collected_on
where p.work_mode = 'remote'
   or p.is_budapest_area
order by p.work_mode, p.company
