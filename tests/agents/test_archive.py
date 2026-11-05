"""The archive: chunking, embeddings, and search in Postgres (spec 005).

The database tests need the Postgres of `make db` and PAX_DB_PASSWORD (or PAX_DATABASE_URL); each
runs in a schema of its own, dropped afterwards. Without a database they are skipped.
"""

import math
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from pax_agentica.agents.archive import Archive, database_url
from pax_agentica.agents.budget import Budget, BudgetExceeded
from pax_agentica.agents.embeddings import GeminiEmbedder, WordHashEmbedder
from pax_agentica.agents.ingest import ROUTINE, Chunk, chunks_from_game, chunks_from_rules
from pax_agentica.agents.recall import RULES_QUESTIONS, game_questions, recall
from pax_agentica.engine import Orders, new_game
from pax_agentica.engine.actions import SendMessage
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.runner import GameRecord, run_game

RULES = Path("docs/game-rules.md").read_text()


@pytest.fixture(scope="module")
def record() -> GameRecord:
    import asyncio

    state = new_game(seed=1, max_turns=12)
    return asyncio.run(run_game(state, {n: GreedyBot(1) for n in state.nations}))


# ---------------------------------------------------------------- chunks


def test_a_game_gives_a_year_chunk_of_news_and_a_chunk_per_crown_that_thought(
    record: GameRecord,
) -> None:
    chunks = chunks_from_game(record, "g1")

    years = [c for c in chunks if c.kind == "year"]
    assert [c.year for c in years] == sorted({c.year for c in years if c.year is not None})
    assert all(c.source == "game:g1" and c.title == f"g1, {c.year}" for c in years)
    thoughts = [c for c in chunks if c.kind == "thoughts"]
    assert {c.nation for c in thoughts} <= set(record.players)


def test_a_year_chunk_leaves_out_routine_and_private_news(record: GameRecord) -> None:
    turn = record.turns[0]
    [chunk] = [
        c for c in chunks_from_game(record, "g1") if c.kind == "year" and c.year == turn.year
    ]

    for event in turn.events:
        kept = event.audience is None and event.kind not in ROUTINE
        assert (event.summary in chunk.text) == kept


def test_letters_go_with_the_thoughts(record: GameRecord) -> None:
    turn = record.turns[0].model_copy(
        update={
            "orders": {
                "france": Orders(
                    actions=[SendMessage(target="spain", text="Trust us.")], thoughts="Lie."
                )
            }
        }
    )
    game = record.model_copy(update={"turns": [turn]})

    [chunk] = [c for c in chunks_from_game(game, "g1") if c.kind == "thoughts"]

    assert chunk.nation == "france"
    assert "Lie." in chunk.text
    assert 'To spain: "Trust us."' in chunk.text


def test_the_rules_are_cut_by_subsection_and_lose_nothing() -> None:
    chunks = chunks_from_rules(RULES)

    assert "rules: War > Fleets" in {c.title for c in chunks}
    for paragraph in RULES.split("\n\n")[3:]:  # after the title and the introduction
        if paragraph.strip() and not paragraph.startswith("#"):
            assert any(paragraph.strip() in c.text for c in chunks), paragraph[:60]


def test_a_chunk_id_follows_its_source_and_text() -> None:
    one = Chunk("rules", "rules", "Sieges take years.")

    assert one.id == Chunk("rules", "rules", "Sieges take years.", title="other").id
    assert one.id != Chunk("rules", "rules", "Sieges take months.").id
    assert one.id != Chunk("game:g1", "rules", "Sieges take years.").id


# ---------------------------------------------------------------- embeddings


def test_the_fake_embedder_is_normalised_and_finds_shared_words() -> None:
    fake = WordHashEmbedder()
    siege, walls, market = fake.embed(
        ["siege walls", "walls under siege", "market prices"], "document"
    )

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert math.isclose(sum(x * x for x in siege), 1.0)
    assert cosine(siege, walls) > cosine(siege, market)


def test_gemini_embeddings_are_paid_for_before_they_are_asked() -> None:
    embedder = GeminiEmbedder(client=None, budget=Budget(1e-9))  # type: ignore[arg-type]

    with pytest.raises(BudgetExceeded):
        embedder.embed(["a" * 1000], "document")


# ---------------------------------------------------------------- the database


def _admin_url() -> str | None:
    try:
        return database_url()
    except ValueError:
        return None


@pytest.fixture
def archive() -> Iterator[Archive]:
    url = _admin_url()
    if url is None:
        pytest.skip("no database: start make db and set PAX_DB_PASSWORD")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"no database: {exc}")
    admin.execute(f"CREATE SCHEMA {schema}")
    sep = "&" if "?" in url else "?"
    store = Archive(f"{url}{sep}options=-csearch_path%3D{schema},public")
    store.set_up()
    yield store
    store.close()
    admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def fill(archive: Archive, chunks: list[Chunk]) -> int:
    fake = WordHashEmbedder()
    new = archive.missing(chunks, fake.model)
    return archive.add(new, fake.embed([c.text for c in new], "document"), fake.model)


def test_ingesting_twice_adds_nothing(archive: Archive) -> None:
    chunks = chunks_from_rules(RULES)

    assert fill(archive, chunks) == len(chunks)
    assert fill(archive, chunks) == 0
    assert archive.count() == {"rules": len(chunks)}


def test_vectors_of_another_model_are_not_compared(archive: Archive) -> None:
    fill(archive, chunks_from_rules(RULES))

    assert archive.search("siege", WordHashEmbedder(dimensions=768), mode="vector")
    assert archive.missing(chunks_from_rules(RULES), "another-model@768") != []


def test_keyword_search_finds_an_exact_name(archive: Archive, record: GameRecord) -> None:
    fill(archive, chunks_from_game(record, "g1"))
    year = next(c for c in chunks_from_game(record, "g1") if c.kind == "year")
    word = next(w for w in year.text.split() if w.istitle() and len(w) > 5)

    hits = archive.search(word, WordHashEmbedder(), k=50, mode="keyword")

    assert hits
    assert all(word.lower() in h.text.lower() for h in hits)


def test_a_search_can_keep_to_one_game_and_the_rules(archive: Archive, record: GameRecord) -> None:
    fill(archive, chunks_from_game(record, "g1") + chunks_from_game(record, "g2"))
    fill(archive, chunks_from_rules(RULES))

    hits = archive.search("war", WordHashEmbedder(), k=30, game="g1")

    assert {h.source for h in hits} <= {"game:g1", "rules"}


def test_hybrid_search_finds_at_least_what_each_kind_finds_alone(
    archive: Archive, record: GameRecord
) -> None:
    fill(archive, chunks_from_game(record, "g1") + chunks_from_rules(RULES))
    questions = [*game_questions(record, "g1"), *RULES_QUESTIONS]

    found = recall(archive, WordHashEmbedder(), questions)

    assert questions
    assert found["hybrid"] >= min(found["keyword"], found["vector"])


def test_the_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAX_DATABASE_URL", raising=False)
    monkeypatch.setenv("PAX_DB_PASSWORD", "secret")

    assert database_url() == "postgresql://pax:secret@127.0.0.1:5433/pax"
    monkeypatch.setenv("PAX_DATABASE_URL", "postgresql://elsewhere/db")
    assert database_url() == "postgresql://elsewhere/db"


def test_without_a_password_there_is_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAX_DATABASE_URL", raising=False)
    monkeypatch.delenv("PAX_DB_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="PAX_DB_PASSWORD"):
        database_url()
