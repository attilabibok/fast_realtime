CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

DO $$
DECLARE
    dbs TEXT[][] := ARRAY[
        ['01', 'PAR'], ['02', 'FTW'], ['03', 'WFS'], ['04', 'AMA'], ['05', 'LBB'],
        ['06', 'ODA'], ['07', 'SJT'], ['08', 'ABL'], ['09', 'WAC'], ['10', 'TYL'],
        ['11', 'LFK'], ['12', 'HOU'], ['13', 'YKM'], ['14', 'AUS'], ['15', 'SAT'],
        ['16', 'CRP'], ['17', 'BRY'], ['18', 'DAL'], ['19', 'ATL'], ['20', 'BMT'],
        ['21', 'PHR'], ['22', 'LRD'], ['23', 'BWD'], ['24', 'ELP'], ['25', 'CHS']
    ];
    db TEXT[];
    server_name TEXT;
    schema_name TEXT;
    db_fullname TEXT;
    tbl TEXT;
    tables TEXT[] := ARRAY[
        's_flood_merge_ar',
        's_flood_road_trim_ln',
        's_flood_road_ln',
        's_bridge_warning_pnt',
        's_lwc_pnt'
    ];
    table_exists BOOLEAN;
BEGIN
    IF current_database() != 'TXFull' THEN
        RAISE EXCEPTION 'This script must be run from TXFull. Current: %', current_database();
    END IF;

    FOREACH db SLICE 1 IN ARRAY dbs LOOP
        server_name := quote_ident(lower(db[1]) || '_srv');
        schema_name := quote_ident('foreign_' || lower(db[1]));
        db_fullname := db[1] || '_' || db[2] || '_realtime_hand';

        -- Create foreign server
        EXECUTE format(
            'CREATE SERVER IF NOT EXISTS %s
             FOREIGN DATA WRAPPER postgres_fdw
             OPTIONS (host %L, dbname %L, port %L);',
            server_name, 'localhost', db_fullname, '5432'
        );

        -- Create user mapping
        EXECUTE format(
            'CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER %s
             OPTIONS (user %L, password %L);',
            server_name, 'admin', 'admin123'
        );

        -- Create schema if needed
        EXECUTE format('CREATE SCHEMA IF NOT EXISTS %s;', schema_name);

        -- Import target tables if missing
        FOREACH tbl IN ARRAY tables LOOP
            BEGIN
                EXECUTE format(
                    'SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %L AND table_name = %L
                    );',
                    lower(schema_name), tbl
                ) INTO table_exists;

                IF NOT table_exists THEN
                    EXECUTE format(
                        'IMPORT FOREIGN SCHEMA public
                         LIMIT TO (%I)
                         FROM SERVER %s INTO %s;',
                        tbl, server_name, schema_name
                    );
                END IF;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE '⚠️ Skipping %.% due to error: %', schema_name, tbl, SQLERRM;
            END;
        END LOOP;
    END LOOP;
END $$;
