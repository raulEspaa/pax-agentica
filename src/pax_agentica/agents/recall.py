"""How well each kind of search finds the right chunk: recall@k on questions with known answers.

Questions about a game are written from its own events, so they need no labelling by hand: "Who
declared war on France in 1511?" must find that year of that game. Questions about the rules are
few and written by hand, with the section that answers them. A question counts as found when an
acceptable chunk is among the first `k`.
"""

from dataclasses import dataclass

from pax_agentica.agents.archive import Archive, Mode
from pax_agentica.agents.embeddings import Embedder
from pax_agentica.runner import GameRecord

K = 5
MODES: tuple[Mode, ...] = ("keyword", "vector", "hybrid")


@dataclass(frozen=True)
class Question:
    text: str
    answers: frozenset[str]  # titles of the chunks that answer it


RULES_QUESTIONS = (
    Question("How do sieges work, and how long do the walls hold?", frozenset({"rules: War"})),
    Question(
        "What does a peace treaty let me demand from the loser?",
        frozenset({"rules: Diplomacy > Peace terms and haggling"}),
    ),
    Question("How can a crown win the game?", frozenset({"rules: Victory"})),
    Question(
        "What can my ruler see of other nations?",
        frozenset({"rules: What you can see (fog of war)"}),
    ),
    Question(
        "Why would other courts band together against me?",
        frozenset({"rules: Diplomacy > Marriages, infamy and coalitions"}),
    ),
    Question("How do I buy and sell goods?", frozenset({"rules: Economy > The European market"})),
)


def game_questions(record: GameRecord, name: str, most: int = 12) -> list[Question]:
    """Up to `most` questions from the game's wars, peaces, cessions and successions."""
    names = {n: s.name for n, s in record.initial.nations.items()}
    out: list[Question] = []
    for turn in record.turns:
        answer = frozenset({f"{name}, {turn.year}"})
        for e in turn.events:
            if e.audience is not None or not e.nations:
                continue
            first = names.get(e.nations[0], e.nations[0])
            other = names.get(e.nations[-1], e.nations[-1])
            text = {
                "war_declared": f"Which court went to war against {other} in {turn.year}?",
                "succession": f"Who took the throne of {first} in {turn.year}?",
                "province_ceded": f"What land did {first} have to give up to {other}?",
            }.get(e.kind.value)
            if text and all(q.text != text for q in out):
                out.append(Question(text, answer))
    return out[:: max(1, len(out) // most)][:most]  # spread over the whole game


def recall(
    archive: Archive, embedder: Embedder, questions: list[Question], k: int = K
) -> dict[Mode, float]:
    """The share of questions with an answer in the first `k`, for each kind of search."""
    found: dict[Mode, float] = {}
    for mode in MODES:
        hits = 0
        for q in questions:
            titles = {h.title for h in archive.search(q.text, embedder, k=k, mode=mode)}
            hits += bool(titles & q.answers)
        found[mode] = hits / len(questions) if questions else 0.0
    return found
