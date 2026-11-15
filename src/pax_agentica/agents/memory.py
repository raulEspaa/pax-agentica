"""A crown's memory of its dealings with every court: treaties kept and broken, wars, tributes,
letters, grudges and audiences (spec 008).

    each year:  view ──> entries_from(view) ──> new ones embedded ──> Chronicle (+ its file)
    the desk:   Chronicle.recall(court, question) ──> "WHAT YOU REMEMBER OF <court>" in a prompt

**Fog of war.** Entries come from the crown's own `NationView` only (`observe` takes nothing
else), and from the audiences it gave itself. A view holds only what that crown witnessed, so the
memory cannot hold more.

**Retrieval.** Within one court, three rankings are merged by Reciprocal Rank Fusion, as in the
archive (spec 005): meaning (cosine of the vectors), words (shared words, for exact names and
provinces) and recency (a ruler remembers last year better than twenty years ago). RRF merges
ranks, not scores, so no scale is tuned against another.

**Money and failure.** Embedding goes through `Embeddings`, which runs the synchronous embedder in
a thread, one call at a time, and turns any failure (a spent budget, a timeout, the provider down)
into `None`: an entry without a vector is still found by its words and its date. A year is never
lost to the memory.

**Untrusted text.** Entries quote letters and audiences, which other courts (and players) wrote.
Each entry is one line, and a prompt that shows them puts them inside tags they cannot close
(`diplomat.fence`), as it does letters.
"""

import asyncio
import json
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel

from pax_agentica.agents.embeddings import Embedder, Purpose
from pax_agentica.engine import NationView
from pax_agentica.engine.events import Event, EventKind
from pax_agentica.engine.model import NationId

TOP_K = 5  # entries recalled per court
RRF_K = 60  # as in the archive (Cormack et al., 2009)
MAX_ENTRY_CHARS = 240  # an entry is a line, not a letter book
EMBED_TIMEOUT_SECONDS = 10.0  # past this, the memory goes on with words alone
VECTOR_DECIMALS = 4  # in the file: enough for a cosine, and a third of the size

# What a ruler remembers of each kind of diplomatic event, and under what word. The proposals
# made and expired, and trades that failed, are left out: the answer is what counts.
KINDS: dict[EventKind, str] = {
    EventKind.MESSAGE: "letter",
    EventKind.PROPOSAL_REJECTED: "refusal",
    EventKind.PROPOSAL_COUNTERED: "counter-offer",
    EventKind.TREATY_SIGNED: "treaty",
    EventKind.TREATY_CANCELLED: "treaty cancelled",
    EventKind.TREATY_EXPIRED: "treaty expired",
    EventKind.TREATY_BROKEN: "betrayal",
    EventKind.CALL_TO_ARMS_IGNORED: "betrayal",
    EventKind.WAR_DECLARED: "war",
    EventKind.JOINED_WAR: "war",
    EventKind.PEACE_SIGNED: "peace",
    EventKind.PROVINCE_CEDED: "peace",
    EventKind.TRIBUTE_PAID: "tribute",
    EventKind.GIFT: "gift",
    EventKind.TRADE_COMPLETED: "trade",
    EventKind.GRUDGE: "grudge",
    EventKind.COALITION_JOINED: "league",
    EventKind.COALITION_DISSOLVED: "league",
}
# Betrayals between other courts are public news, and tell what a court's word is worth.
_REPUTATION = {EventKind.TREATY_BROKEN, EventKind.CALL_TO_ARMS_IGNORED}
_STOP_WORDS = "the and for with from that this you your its his her their our are was were has \
have not but all any who what why how will would into than then them they"
_STOP = frozenset(_STOP_WORDS.split(" "))


class Entry(BaseModel):
    """One line of a crown's memory, about one court."""

    key: str  # what makes it the same entry when a view shows it again
    turn: int
    court: NationId  # the court it is about
    kind: str  # letter, treaty, betrayal, war, peace, tribute, grudge, audience...
    text: str  # one line, dated, the court named by its id
    vector: list[float] | None = None  # None: not embedded (no embedder, or it failed)


def _line(text: str) -> str:
    """On one line, and short: a quoted letter cannot start a line of its own in a prompt."""
    return " ".join(text.split())[:MAX_ENTRY_CHARS]


def _year(view: NationView, turn: int) -> int:
    return view.rules.start_year + turn - 1


def _from_event(view: NationView, e: Event, court: NationId) -> Entry | None:
    kind = KINDS.get(e.kind)
    if kind is None:
        return None
    if e.kind == EventKind.MESSAGE:
        sender = str(e.data.get("sender", ""))
        who = "you wrote to " + court if sender == view.me.id else f"{court} wrote"
        said = f'{who}: "{" ".join(str(e.data.get("text", "")).split())}"'
    else:
        said = e.summary
        if view.me.id not in e.nations:
            said += " (not against you)"
    text = _line(f"{_year(view, e.turn)}, {kind}: {said}")
    key = f"{court}|{e.turn}|{e.kind.value}|{text}"
    return Entry(key=key, turn=e.turn, court=court, kind=kind, text=text)


def entries_from(view: NationView) -> list[Entry]:
    """Every entry this view gives about the courts: its correspondence with each, the betrayals
    and tributes of last year, and the grudges on both sides. Only what the view shows."""
    me = view.me
    out: list[Entry] = []
    for court in view.nations:
        for e in court.correspondence:
            if entry := _from_event(view, e, court.id):
                out.append(entry)
        for g in court.remembers:
            text = _line(f"{g.since_year}, grudge: {court.id} will not forget that you {g.reason}")
            key = f"{court.id}|held|{g.reason}|{g.since_year}"
            turn = g.since_year - view.rules.start_year + 1
            out.append(Entry(key=key, turn=turn, court=court.id, kind="grudge", text=text))
    for g in me.grudges:
        text = _line(f"{g.since_year}, grudge: you will not forget that {g.against} {g.reason}")
        key = f"{g.against}|mine|{g.reason}|{g.since_year}"
        turn = g.since_year - view.rules.start_year + 1
        out.append(Entry(key=key, turn=turn, court=g.against, kind="grudge", text=text))
    courts = {n.id for n in view.nations}
    for e in view.last_turn_events:
        whom: str | None
        if e.kind == EventKind.TRIBUTE_PAID and me.id in e.nations:
            whom = next((n for n in e.nations if n != me.id), None)
        elif e.kind in _REPUTATION and me.id not in e.nations and e.nations:
            whom = e.nations[0]  # the one who broke its word
        else:
            continue
        if whom in courts and (entry := _from_event(view, e, whom)):
            out.append(entry)
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP}


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))  # both normalised


def _fuse(*rankings: Sequence[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores


class Embeddings:
    """An `Embedder` for async code: in a thread, one call at a time (the embedder's rate window
    and the budget's file are not made for threads), and `None` instead of an error."""

    def __init__(self, embedder: Embedder, timeout: float = EMBED_TIMEOUT_SECONDS) -> None:
        self.embedder = embedder
        self.timeout = timeout
        self.failures: list[str] = []  # why each failed call failed, for tests and logs
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return self.embedder.model

    async def vectors(self, texts: list[str], purpose: Purpose) -> list[list[float]] | None:
        if not texts:
            return []
        try:
            async with asyncio.timeout(self.timeout):
                return await asyncio.to_thread(self._embed, texts, purpose)
        except Exception as exc:  # a spent budget, a timeout, the provider down: words will do
            self.failures.append(f"{type(exc).__name__} {exc}"[:200])
            return None

    def _embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        with self._lock:
            return self.embedder.embed(texts, purpose)


class Chronicle:
    """One crown's memory at one table. Kept in a file at `path`, if it has one, after every
    change, and read back from it when made again (a table unloads; the server restarts)."""

    def __init__(self, embeddings: Embeddings | None = None, path: Path | None = None) -> None:
        self.embeddings = embeddings
        self.path = path
        self.entries: list[Entry] = []
        self._keys: set[str] = set()
        if path is not None and path.exists():
            self._load(path)

    # ------------------------------------------------------------ writing

    async def observe(self, view: NationView) -> list[Entry]:
        """Remember what this year's view shows that is not remembered yet. Returns the new."""
        new: dict[str, Entry] = {}
        for entry in entries_from(view):
            if entry.key not in self._keys:
                new.setdefault(entry.key, entry)
        await self._add(list(new.values()))
        return list(new.values())

    async def remember_audience(
        self, view: NationView, guest: NationId, speaker: str, said: str, answered: str
    ) -> Entry:
        """An audience this crown gave: what the other court's envoy said, and the answer."""
        heard = " ".join(said.split())[:120]
        reply = " ".join(answered.split())[:100]
        text = _line(
            f'{view.year}, audience: {guest} ({speaker}) said "{heard}"; you answered "{reply}"'
        )
        key = f"{guest}|audience|{view.turn}|{len(self.entries)}|{text}"
        entry = Entry(key=key, turn=view.turn, court=guest, kind="audience", text=text)
        await self._add([entry])
        return entry

    async def _add(self, entries: list[Entry]) -> None:
        if not entries:
            return
        if self.embeddings is not None:
            vectors = await self.embeddings.vectors([e.text for e in entries], "document")
            if vectors is not None and len(vectors) == len(entries):
                entries = [
                    e.model_copy(update={"vector": v})
                    for e, v in zip(entries, vectors, strict=True)
                ]
        for entry in entries:
            if entry.key not in self._keys:
                self._keys.add(entry.key)
                self.entries.append(entry)
        self.save()

    # ------------------------------------------------------------ reading

    def about(self, court: NationId) -> list[Entry]:
        return [e for e in self.entries if e.court == court]

    def audiences_since(self, turn: int) -> set[NationId]:
        """The courts this crown gave an audience to from `turn` on."""
        return {e.court for e in self.entries if e.kind == "audience" and e.turn >= turn}

    async def recall(self, court: NationId, question: str, k: int = TOP_K) -> list[Entry]:
        """The `k` entries about `court` that best answer `question`, best first."""
        return (await self.recall_all({court: question}, k))[court]

    async def recall_all(
        self, questions: Mapping[NationId, str], k: int = TOP_K
    ) -> dict[NationId, list[Entry]]:
        """`recall` for several courts, with every question embedded in one call."""
        asking = [c for c in questions if any(e.vector is not None for e in self.about(c))]
        vectors = None
        if asking and self.embeddings is not None:
            vectors = await self.embeddings.vectors([questions[c] for c in asking], "query")
        query = dict(zip(asking, vectors, strict=True)) if vectors else {}
        return {c: self._rank(c, q, query.get(c), k) for c, q in questions.items()}

    def _rank(
        self, court: NationId, question: str, query: list[float] | None, k: int
    ) -> list[Entry]:
        mine = self.about(court)
        recent = [e.key for e in sorted(mine, key=lambda e: -e.turn)]
        asked = _words(question)
        overlap = {e.key: len(asked & _words(e.text)) for e in mine}
        by_words = sorted(
            (e for e in mine if overlap[e.key]), key=lambda e: (-overlap[e.key], -e.turn)
        )
        rankings = [recent, [e.key for e in by_words]]
        if query is not None:
            embedded = [e for e in mine if e.vector is not None]
            by_meaning = sorted(embedded, key=lambda e: -_cosine(query, e.vector or []))
            rankings.append([e.key for e in by_meaning])
        scores = _fuse(*rankings)
        return sorted(mine, key=lambda e: (-scores.get(e.key, 0.0), -e.turn))[:k]

    # ------------------------------------------------------------ the file

    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "model": self.embeddings.model if self.embeddings else None,
            "entries": [
                e.model_dump()
                | {"vector": [round(x, VECTOR_DECIMALS) for x in e.vector] if e.vector else None}
                for e in self.entries
            ],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # a memory that cannot be written is still held: the game goes on

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = [Entry.model_validate(e) for e in data["entries"]]
        except (OSError, ValueError, KeyError, TypeError):
            return  # a file we cannot read: the crown starts forgetful, and plays on
        model = self.embeddings.model if self.embeddings else None
        if data.get("model") != model:  # vectors of another model must never be compared
            entries = [e.model_copy(update={"vector": None}) for e in entries]
        self.entries = entries
        self._keys = {e.key for e in entries}


def question_about(view: NationView, court: NationId, extra: Iterable[str] = ()) -> str:
    """What a ruler asks its memory about a court: its dealings, and what it says lately."""
    lately = [
        " ".join(str(e.data.get("text", "")).split())
        for n in view.nations
        if n.id == court
        for e in n.correspondence
        if e.turn >= view.turn - 1 and e.kind == EventKind.MESSAGE
    ]
    parts = [f"{court}: treaties, betrayals, wars, tributes and promises", *lately, *extra]
    return " ".join(parts)[:1000]
