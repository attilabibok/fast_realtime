-- Enable FDW extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Create foreign servers, mappings, and import table
DO $$
DECLARE
    dbs TEXT[][] := ARRAY[
        ['01', 'PAR', 'PAR'],
        ['02', 'FTW', 'FTW'],
        ['03', 'WFS', 'WFS'],
        ['04', 'AMA', 'AMA'],
        ['05', 'LBB', 'LBB'],
        ['06', 'ODA', 'ODA'],
        ['07', 'SJT', 'SJT'],
        ['08', 'ABL', 'ABL'],
        ['09', 'WAC', 'WAC'],
        ['10', 'TYL', 'TYL'],
        ['11', 'LFK', 'LFK'],
        ['12', 'HOU', 'HOU'],
        ['13', 'YKM', 'YKM'],
        ['14', 'AUS', 'AUS'],
        ['15', 'SAT', 'SAT'],
        ['16', 'CRP', 'CRP'],
        ['17', 'BRY', 'BRY'],
        ['18', 'DAL', 'DAL'],
        ['19', 'ATL', 'ATL'],
        ['20', 'BMT', 'BMT'],
        ['21', 'PHR', 'PHR'],
        ['22', 'LRD', 'LRD'],
        ['23', 'BWD', 'BWD'],
        ['24', 'ELP', 'ELP'],
        ['25', 'CHS', 'CHS']
    ];
    db TEXT[];
    server_name TEXT;
    schema_name TEXT;
BEGIN
    FOREACH db SLICE 1 IN ARRAY dbs LOOP
        -- Use 3-letter code for identifiers
        server_name := quote_ident(lower(db[1]) || '_srv');
        schema_name := quote_ident('foreign_' || lower(db[1]));

        EXECUTE format('
            CREATE SERVER IF NOT EXISTS %s
            FOREIGN DATA WRAPPER postgres_fdw
            OPTIONS (host %L, dbname %L, port %L);
        ', server_name, 'localhost', db[2], '5432');

        EXECUTE format('
            CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER %s
            OPTIONS (user %L, password %L);
        ', server_name, 'admin', 'admin123');

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
