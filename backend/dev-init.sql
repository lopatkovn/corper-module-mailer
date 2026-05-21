-- Initialise schema in dev DB. Runs once at first container start
-- (mounted at /docker-entrypoint-initdb.d/01_init.sql).
CREATE SCHEMA IF NOT EXISTS mailer AUTHORIZATION dev;
GRANT ALL PRIVILEGES ON SCHEMA mailer TO dev;
