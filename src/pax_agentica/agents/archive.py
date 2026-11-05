"""The archive: chunks of finished games and of the rules in Postgres, found by meaning and by word.

One table holds the text, its vector (pgvector) and its words (a `tsvector` Postgres keeps itself):

- **Vector search** finds what a question means, in other words: "who betrayed Spain" finds a
  year where France broke its alliance. An HNSW index keeps it fast as the archive grows.
- **Keyword search** finds exact names that vectors blur: `flanders`, a treaty, a year.
- **Hybrid search** merges both rankings with Reciprocal Rank Fusion: each chunk scores
  1/(60 + its rank) in each list. Ranks, not scores, so the two scales never need matching.

`pax ingest` measures all three on the same questions (see `recall`), so the choice is shown, not
assumed.
"""

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from pax_agentica.agents.embeddings import DIMENSIONS, Embedder
from pax_agentica.agents.ingest import Chunk

type Mode = Literal["hybrid", "vector", "keyword"]

RRF_K = 60  # the constant of the original paper (Cormack et al., 2009)
CANDIDATES = 40  # how deep each list goes before they are merged

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    id text PRIMARY KEY,                 -- a hash of source and text: ingesting twice adds nothing
    source text NOT NULL,                -- "game:<name>" or "rules"
    kind text NOT NULL,                  -- year, thoughts or rules
    game text,
    year integer,
    nation text,
    title text NOT NULL,                 -- how a citation names it
    text text NOT NULL,
    embedding vector({DIMENSIONS}) NOT NULL,
    embedding_model text NOT NULL,       -- vectors of different models must never be compared
    words tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    ingested_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_words ON chunks USING gin (words);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source, year, nation);
"""

# Postgres joins a question's words with AND, so a natural question rarely matches whole; OR
# lets every word count and the ranking sort out the rest.
# The words are stemmed once, by the 'english' parser; 'simple' reads the stems back unchanged.
_ANY_WORD = "to_tsquery('simple', replace(plainto_tsquery('english', %(text)s)::text, '&', '|'))"

_VECTOR = """
SELECT id, row_number() OVER (ORDER BY embedding <=> %(vector)s) AS rank
FROM chunks WHERE embedding_model = %(model)s {where}
ORDER BY embedding <=> %(vector)s LIMIT %(depth)s
"""

_KEYWORD = (
    f"SELECT id, row_number() OVER (ORDER BY ts_rank_cd(words, q) DESC) AS rank "
    f"FROM chunks, {_ANY_WORD} AS q WHERE words @@ q {{where}} "
    "ORDER BY ts_rank_cd(words, q) DESC LIMIT %(depth)s"
)


def database_url() -> str:
    """PAX_DATABASE_URL, or the database of `make db` with the password in PAX_DB_PASSWORD."""
    if url := os.environ.get("PAX_DATABASE_URL"):
        return url
    password = os.environ.get("PAX_DB_PASSWORD")
    if not password:
        raise ValueError("set PAX_DATABASE_URL, or PAX_DB_PASSWORD for the database of make db")
    return f"postgresql://pax:{password}@127.0.0.1:5433/pax"


@dataclass(frozen=True)
class Hit:
    id: str
    title: str
    text: str
    source: str
    kind: str
    year: int | None
    nation: str | None
    score: float


class Archive:
    """The chunks table on one connection. `url` is a Postgres URL, such as `database_url()`."""

    def __init__(self, url: str) -> None:
        self._db = psycopg.connect(url, autocommit=True)
        self._db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._db)

    def close(self) -> None:
        self._db.close()

    def set_up(self) -> None:
        self._db.execute(SCHEMA)

    def missing(self, chunks: Iterable[Chunk], model: str) -> list[Chunk]:
        """The chunks not yet stored with vectors of this model: only those need embedding."""
        wanted = {c.id: c for c in chunks}
        found = self._db.execute(
            "SELECT id FROM chunks WHERE id = ANY(%s) AND embedding_model = %s",
            (list(wanted), model),
        ).fetchall()
        stored = {row[0] for row in found}
        return [c for i, c in wanted.items() if i not in stored]

    def add(self, chunks: Sequence[Chunk], vectors: Sequence[list[float]], model: str) -> int:
        """Store chunks with their vectors; a chunk already there is replaced. Returns how many."""
        rows = [
            (c.id, c.source, c.kind, c.game, c.year, c.nation, c.title, c.text, Vector(v), model)
            for c, v in zip(chunks, vectors, strict=True)
        ]
        with self._db.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO chunks (id, source, kind, game, year, nation, title, text,
                                    embedding, embedding_model)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding,
                    embedding_model = EXCLUDED.embedding_model, ingested_at = now()
                """,
                rows,
            )
        return len(rows)

    def count(self) -> dict[str, int]:
        rows = self._db.execute("SELECT kind, count(*) FROM chunks GROUP BY kind").fetchall()
        return {kind: n for kind, n in rows}

    def search(
        self,
        question: str,
        embedder: Embedder,
        k: int = 5,
        mode: Mode = "hybrid",
        game: str | None = None,
    ) -> list[Hit]:
        """The `k` chunks that best answer `question`, best first; `game` keeps to one game and
        the rules."""
        params: dict[str, Any] = {"text": question, "model": embedder.model, "depth": CANDIDATES}
        where = ""
        if game is not None:
            where = "AND (game = %(game)s OR source = 'rules')"
            params["game"] = game
        if mode != "keyword":
            [vector] = embedder.embed([question], "query")
            params["vector"] = Vector(vector)
        lists = {
            "hybrid": [_VECTOR, _KEYWORD],
            "vector": [_VECTOR],
            "keyword": [_KEYWORD],
        }[mode]
        ranked = " UNION ALL ".join(f"({q.format(where=where)})" for q in lists)
        rows = self._db.cursor(row_factory=dict_row).execute(
            f"""
            WITH ranked AS ({ranked})
            SELECT c.id, c.title, c.text, c.source, c.kind, c.year, c.nation,
                   sum(1.0 / ({RRF_K} + ranked.rank))::float8 AS score
            FROM ranked JOIN chunks c USING (id)
            GROUP BY c.id ORDER BY score DESC, c.id LIMIT %(k)s
            """,
            {**params, "k": k},
        )
        return [Hit(**row) for row in rows.fetchall()]
