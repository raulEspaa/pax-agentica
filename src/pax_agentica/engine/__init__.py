"""The game engine: pure, deterministic, no I/O and no LLM.

The whole public surface a player or a runner needs:

    state = new_game(seed=1)
    view = view_for(state, "france")          # fog of war: what France may know
    orders = Orders(actions=[...])            # what France wants to do
    state = resolve_turn(state, {"france": orders, ...})
"""

from pax_agentica.engine.actions import Action, Orders
from pax_agentica.engine.events import Event, EventKind
from pax_agentica.engine.model import GameState, NationId, ProvinceId, Resources, Rules
from pax_agentica.engine.resolve import GameOverError, resolve_turn
from pax_agentica.engine.scenario import new_game
from pax_agentica.engine.view import NationView, view_for

__all__ = [
    "Action",
    "Event",
    "EventKind",
    "GameOverError",
    "GameState",
    "NationId",
    "NationView",
    "Orders",
    "ProvinceId",
    "Resources",
    "Rules",
    "new_game",
    "resolve_turn",
    "view_for",
]
