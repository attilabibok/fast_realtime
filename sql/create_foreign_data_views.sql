-- Enable FDW extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Create foreign servers, mappings, and import table
DO $$
DECLARE
    dbs TEXT[][] := ARRAY[
        ['08', 'ABL', 'ABL'],
        ['04', 'AMA', 'AMA'],
        ['19', 'ATL', 'ATL'],
        ['14', 'AUS', 'AUS'],
        ['20', 'BMT', 'BMT'],
        ['17', 'BRY', 'BRY'],
        ['23', 'BWD', 'BWD'],
        ['25', 'CHS', 'CHS'],
        ['16', 'CRP', 'CRP'],
        ['18', 'DAL', 'DAL'],
        ['24', 'ELP', 'ELP'],
        ['02', 'FTW', 'FTW'],
        ['11', 'LFK', 'LFK'],
        ['06', 'ODA', 'ODA'],
        ['01', 'PAR', 'PAR'],
        ['21', 'PHR', 'PHR'],
        ['15', 'SAT', 'SAT'],
        ['07', 'SJT', 'SJT'],
        ['13', 'YKM', 'YKM']
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
