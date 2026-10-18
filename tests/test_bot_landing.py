"""The greedy bot carries its armies over a sea it commands onto an enemy's shore."""

import asyncio

from pax_agentica.engine import GameState, Orders, resolve_turn, view_for
from pax_agentica.engine.actions import Attack, DeclareWar
from pax_agentica.engine.model import Ship, UnitKind
from pax_agentica.players.greedy_bot import GreedyBot


def test_a_bot_with_the_channel_lands_in_england(state: GameState) -> None:
    state.nations["england"].fleets = {}
    for p in state.provinces.values():  # France's whole host waits in Normandy
        if p.owner == "france":
            p.set_army({})
    state.provinces["normandy"].set_army({UnitKind.INFANTRY: 12})
    state.nations["france"].fleets = {"channel": {Ship.GALLEON: 6}}
    war = resolve_turn(state, {"france": Orders(actions=[DeclareWar(target="england")])})
    war.nations["france"].fleets = {"channel": {Ship.GALLEON: 6}}
    war.provinces["east_anglia"].set_army({UnitKind.INFANTRY: 1})
    landed = []
    for seed in range(4):
        orders = asyncio.run(GreedyBot(seed).decide(view_for(war, "france")))
        attacks = [a for a in orders.actions if isinstance(a, Attack)]
        landed += [a for a in attacks if a.origin == "normandy" and a.target != "london"]
        assert all(a.regiments <= 12 for a in attacks if a.origin == "normandy")
    assert landed
    assert {a.target for a in landed} <= {"east_anglia", "devon"}
