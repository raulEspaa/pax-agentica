"""The game loop: ask every ruler for orders, resolve the turn, repeat until someone wins.

This is the only place where the pure engine meets the outside world. Rulers decide in parallel
(`asyncio.gather`), and a ruler that crashes or takes too long simply does nothing that turn:
one bad answer from an LLM must not stop the game.
"""

import asyncio
from collections.abc import Callable, Mapping

from pydantic import BaseModel, Field

from pax_agentica.engine import (
    Event,
    GameState,
    NationId,
    NationView,
    Orders,
    Resources,
    resolve_turn,
    view_for,
)
from pax_agentica.engine.mechanics import province_output
from pax_agentica.engine.model import TreatyKind
from pax_agentica.players import Player


class ProvinceSnapshot(BaseModel):
    owner: NationId | None
    controller: NationId | None = None  # an occupier in a war
    troops: int
    development: int
    fort: int
    unrest: int
    buildings: list[str]
    output: Resources  # per turn, before the stability modifier


class NationSnapshot(BaseModel):
    alive: bool
    capital: str
    resources: Resources
    stability: int
    score: int
    provinces: int
    regiments: int
    at_war_with: list[NationId]
    allies: list[NationId]
    technology: dict[str, int]
    ruler: str = ""  # "King Louis XII"
    stances: dict[NationId, str] = Field(default_factory=dict)  # declared friends and rivals


class GeneralSnapshot(BaseModel):
    name: str
    nation: NationId
    skill: int
    province: str


class Snapshot(BaseModel):
    """The world after a turn, compact enough to store one per turn for replays."""

    provinces: dict[str, ProvinceSnapshot]
    nations: dict[NationId, NationSnapshot]
    generals: list[GeneralSnapshot] = Field(default_factory=list)


class TurnRecord(BaseModel):
    turn: int
    year: int
    orders: dict[NationId, Orders]
    errors: dict[NationId, str] = Field(default_factory=dict)  # rulers that failed to answer
    events: list[Event]
    after: Snapshot


class GameRecord(BaseModel):
    """Everything needed to replay, watch or analyse a game."""

    players: dict[NationId, str]
    initial: GameState
    start: Snapshot
    turns: list[TurnRecord] = Field(default_factory=list)
    winner: NationId | None = None


def snapshot(state: GameState) -> Snapshot:
    return Snapshot(
        provinces={
            pid: ProvinceSnapshot(
                owner=p.owner,
                controller=p.controller,
                troops=p.troops,
                development=p.development,
                fort=p.fort,
                unrest=p.unrest,
                buildings=[b.value for b in p.buildings],
                output=province_output(state, pid),
            )
            for pid, p in state.provinces.items()
        },
        nations={
            nid: NationSnapshot(
                alive=n.alive,
                capital=n.capital,
                resources=n.resources,
                stability=n.stability,
                score=state.score(nid),
                provinces=len(state.provinces_of(nid)),
                regiments=state.troops_of(nid),
                at_war_with=state.enemies_of(nid),
                allies=state.partners(nid, TreatyKind.ALLIANCE),
                technology={b.value: level for b, level in n.technology.items()},
                ruler=f"{n.ruler.title} {n.ruler.name}" if n.ruler else "",
                stances={k: v.value for k, v in n.stances.items()},
            )
            for nid, n in state.nations.items()
        },
        generals=[
            GeneralSnapshot(name=g.name, nation=g.nation, skill=g.skill, province=g.province)
            for g in state.generals
        ],
    )


async def _ask(player: Player, view: NationView, timeout: float | None) -> Orders | str:
    try:
        return await asyncio.wait_for(player.decide(view), timeout)
    except TimeoutError:
        return f"timed out after {timeout}s"
    except Exception as exc:  # a broken ruler forfeits its turn, the game goes on
        return f"{type(exc).__name__}: {exc}"


async def play_turn(
    state: GameState, players: Mapping[NationId, Player], timeout: float | None = None
) -> tuple[GameState, TurnRecord]:
    alive = [n for n in state.alive_nations() if n in players]
    answers = await asyncio.gather(*(_ask(players[n], view_for(state, n), timeout) for n in alive))
    orders: dict[NationId, Orders] = {}
    errors: dict[NationId, str] = {}
    for nation, answer in zip(alive, answers, strict=True):
        if isinstance(answer, Orders):
            orders[nation] = answer
        else:
            errors[nation] = answer
    new_state = resolve_turn(state, orders)
    record = TurnRecord(
        turn=state.turn,
        year=state.year,
        orders=orders,
        errors=errors,
        events=new_state.last_events,
        after=snapshot(new_state),
    )
    return new_state, record


async def run_game(
    state: GameState,
    players: Mapping[NationId, Player],
    *,
    timeout: float | None = None,
    on_turn: Callable[[TurnRecord, GameState], None] | None = None,
) -> GameRecord:
    """Play `state` to the end. `players` maps every nation to its ruler."""
    missing = set(state.nations) - set(players)
    if missing:
        raise ValueError(f"no player for: {', '.join(sorted(missing))}")
    record = GameRecord(
        players={n: p.name for n, p in players.items()},
        initial=state,
        start=snapshot(state),
    )
    while not state.finished:
        state, turn = await play_turn(state, players, timeout)
        record.turns.append(turn)
        if on_turn is not None:
            on_turn(turn, state)
    record.winner = state.winner
    return record
