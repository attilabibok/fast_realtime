-- Enable FDW extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Create foreign servers, mappings, and import table
DO $$
DECLARE
    dbs TEXT[][] := ARRAY[
        ['01', 'PAR'],
        ['02', 'FTW'],
        ['03', 'WFS'],
        ['04', 'AMA'],
        ['05', 'LBB'],
        ['06', 'ODA'],
        ['07', 'SJT'],
        ['08', 'ABL'],
        ['09', 'WAC'],
        ['10', 'TYL'],
        ['11', 'LFK'],
        ['12', 'HOU'],
        ['13', 'YKM'],
        ['14', 'AUS'],
        ['15', 'SAT'],
        ['16', 'CRP'],
        ['17', 'BRY'],
        ['18', 'DAL'],
        ['19', 'ATL'],
        ['20', 'BMT'],
        ['21', 'PHR'],
        ['22', 'LRD'],
        ['23', 'BWD'],
        ['24', 'ELP'],
        ['25', 'CHS']
    ];
    db TEXT[];
    server_name TEXT;
    schema_name TEXT;
    db_fullname TEXT;
BEGIN
    FOREACH db SLICE 1 IN ARRAY dbs LOOP
        -- Construct names
        server_name := quote_ident(lower(db[1]) || '_srv');                 -- e.g., '01_srv'
        schema_name := quote_ident('foreign_' || lower(db[1]));            -- e.g., 'foreign_01'
        db_fullname := db[1] || '_' || db[2] || '_realtime_hand';          -- e.g., '01_PAR_realtime_hand'

        -- Create server
        EXECUTE format('
            CREATE SERVER IF NOT EXISTS %s
            FOREIGN DATA WRAPPER postgres_fdw
            OPTIONS (host %L, dbname %L, port %L);
        ', server_name, 'localhost', db_fullname, '5432');

        -- Create user mapping
        EXECUTE format('
            CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER %s
            OPTIONS (user %L, password %L);
        ', server_name, 'admin', 'admin123');

        -- Create schema and import table
        EXECUTE format('
            CREATE SCHEMA IF NOT EXISTS %s;
        ', schema_name);

        EXECUTE format('
            IMPORT FOREIGN SCHEMA public
            LIMIT TO (s_flood_merge_ar)
            FROM SERVER %s INTO %s;
        ', server_name, schema_name);
    END LOOP;
END $$;
