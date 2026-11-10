-- One row per posting: renamed, trimmed and with a few derived fields.
-- No filtering here; every raw row comes through.

with source as (

    select * from {{ source('raw', 'job_postings') }}

),

renamed as (

    select
        id                                        as job_id,
        source,
        trim(title)                               as title,
        trim(company)                             as company,
        location,
        case place_label
            when 'Tavmunka/Remote'          then 'remote'
            when 'Hibrid/Home office'       then 'hybrid'
            when 'Barmilyen (helyszini is)' then 'any'
            else 'unknown'
        end                                       as work_mode,
        coalesce(location ilike '%budapest%'
                 or location ilike 'pest megye%'
                 OR location ilike '%kerület%', false) as is_budapest_area,
        salary_info,
        salary_info is not null                   as has_salary,
        techs                                     as techs_raw,
        description,
        length(description)                       as description_length,
        url,
        collected_on,
        loaded_at,
        source_file,
        coalesce(description ilike '%python%', false)	AS has_python

    from source

)

select * from renamed
