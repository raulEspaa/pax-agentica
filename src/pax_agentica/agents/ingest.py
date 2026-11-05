"""Ingestion: finished games and the rules, cut into chunks that a search can find and cite.

A chunk is one thing a question can be about, so the cut follows the game, not a character count:

    year      what all Europe saw happen in one year of one game (public events only)
    thoughts  what one crown thought, ordered and wrote in one year: the "why" behind the events
    rules     one section of docs/game-rules.md, split further only if it is long

Each chunk's id is a hash of its source and text, so ingesting the same game twice adds nothing,
and a changed rule section is a new chunk. Thoughts are secret in the game; the archive is read
after the game, by a historian, so it may hold them. A ruler must never read it during a game.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pax_agentica.engine.actions import SendMessage
from pax_agentica.runner import GameRecord

type Kind = Literal["year", "thoughts", "rules"]

MAX_RULES_CHARS = 3000  # a section longer than this is cut at paragraphs

# Public events too frequent to tell one year from another: about half of all of them.
ROUTINE = {
    "stability_changed", "built", "developed", "researched", "event_decided", "royal_act",
    "ships_built", "policy_set", "advisor_hired", "market_trade", "taxes_set", "recruited",
    "focus_set", "proposal_made", "prestige_changed", "trade_completed", "infamy", "agenda",
}  # fmt: skip


@dataclass(frozen=True)
class Chunk:
    source: str  # "game:<name>" or "rules"
    kind: Kind
    text: str
    game: str | None = None
    year: int | None = None
    nation: str | None = None
    title: str = ""  # how a citation names it

    @property
    def id(self) -> str:
        return hashlib.sha256(f"{self.source}\n{self.text}".encode()).hexdigest()[:24]


def chunks_from_game(record: GameRecord, name: str) -> list[Chunk]:
    """A year chunk per year with public news, and a thoughts chunk per crown and year."""
    source = f"game:{name}"
    names = {n: s.name for n, s in record.initial.nations.items()}
    out: list[Chunk] = []
    for turn in record.turns:
        news = [e.summary for e in turn.events if e.audience is None and e.kind not in ROUTINE]
        if news:
            text = f"{turn.year}, all Europe saw:\n" + "\n".join(news)
            out.append(Chunk(source, "year", text, name, turn.year, None, f"{name}, {turn.year}"))
        for nation, orders in sorted(turn.orders.items()):
            letters = [
                f'To {a.target}: "{a.text}"' for a in orders.actions if isinstance(a, SendMessage)
            ]
            said = [orders.thoughts.strip(), *letters]
            if not any(said):
                continue
            ruler = f"{names.get(nation, nation)} ({record.players.get(nation, '?')})"
            text = f"{turn.year}, {ruler}, in private: " + "\n".join(s for s in said if s)
            title = f"{name}, {turn.year}, {nation}"
            out.append(Chunk(source, "thoughts", text, name, turn.year, nation, title))
    return out


def chunks_from_rules(markdown: str) -> list[Chunk]:
    """One chunk per `###` subsection (or `##` section without any), cut at paragraphs when it
    runs long. The title says where it sits: "Economy > Taxes"."""
    out: list[Chunk] = []
    section = ""
    for block in re.split(r"(?m)^(?=##+ )", markdown):
        heading = block.splitlines()[0] if block.strip() else ""
        if heading.startswith("## "):
            section = heading[3:].strip()
        elif not heading.startswith("### "):
            continue  # what comes before the first section
        title = section if heading.startswith("## ") else f"{section} > {heading[4:].strip()}"
        if len(block.splitlines()) <= 2 and heading.startswith("## "):
            continue  # a section heading with nothing but its subsections below it
        part = ""
        for paragraph in block.split("\n\n"):
            if part and len(part) + len(paragraph) > MAX_RULES_CHARS:
                out.append(_rules_chunk(title, part))
                part = f"{title} (continued)\n\n"
            part += paragraph + "\n\n"
        out.append(_rules_chunk(title, part))
    return out


def _rules_chunk(heading: str, text: str) -> Chunk:
    return Chunk("rules", "rules", text.strip(), title=f"rules: {heading}")
