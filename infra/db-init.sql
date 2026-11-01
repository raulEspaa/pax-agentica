-- Runs once, when the database is first created. pgvector ships in the image but each database
-- has to turn it on.
CREATE EXTENSION IF NOT EXISTS vector;
