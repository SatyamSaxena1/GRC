-- Runs once, only against a fresh postgres data volume (docker-entrypoint-initdb.d
-- semantics). Authentik gets its own database in the same postgres container
-- rather than a second container — one less thing to run for local dev.
CREATE DATABASE authentik;
