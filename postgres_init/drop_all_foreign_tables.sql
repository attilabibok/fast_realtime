DO $$
DECLARE
    i INT;
    schema_name TEXT;
BEGIN
    FOR i IN 1..25 LOOP
        schema_name := format('foreign_%s', to_char(i, 'FM00'));
        EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE;', schema_name);
        RAISE NOTICE 'Dropped schema %', schema_name;
    END LOOP;
END $$;
