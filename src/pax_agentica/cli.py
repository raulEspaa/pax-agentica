"""`pax`: play, inspect and benchmark games from the terminal."""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pax_agentica.engine import EventKind, GameState, Orders, new_game, view_for
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.random_bot import RandomBot
from pax_agentica.runner import GameRecord, TurnRecord, run_game

BOTS = {"greedy": GreedyBot, "random": RandomBot}

HEADLINES = {
    EventKind.WAR_DECLARED,
    EventKind.JOINED_WAR,
    EventKind.CALL_TO_ARMS_IGNORED,
    EventKind.TREATY_SIGNED,
    EventKind.TREATY_BROKEN,
    EventKind.TREATY_CANCELLED,
    EventKind.PEACE_SIGNED,
    EventKind.TRADE_COMPLETED,
    EventKind.GIFT,
    EventKind.PROVINCE_CAPTURED,
    EventKind.CAPITAL_MOVED,
    EventKind.NATION_ELIMINATED,
    EventKind.GAME_OVER,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler = {
        "play": _play,
        "view": _view,
        "schema": _schema,
        "map": _map,
        "bench": _bench,
        "serve": _serve,
    }[args.command]
    return handler(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pax", description="Pax Agentica: Europe, 1500.")
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play a game and narrate it")
    play.add_argument("--seed", type=int, default=1)
    play.add_argument("--turns", type=int, default=50, help="turn limit (default 50)")
    play.add_argument(
        "--bot", choices=sorted(BOTS), default="greedy", help="ruler for every nation"
    )
    play.add_argument(
        "--player",
        action="append",
        default=[],
        metavar="NATION=BOT",
        help="override one nation's ruler, e.g. --player france=random",
    )
    play.add_argument("--verbose", action="store_true", help="also show battles and diplomacy")
    play.add_argument("--quiet", action="store_true", help="only the final standings")
    play.add_argument("--save", type=Path, help="write the full game record (JSON)")
    play.add_argument("--html", type=Path, help="write a self-contained HTML replay")

    view = sub.add_parser("view", help="print what one nation sees (JSON), e.g. to design prompts")
    view.add_argument("nation")
    view.add_argument("--seed", type=int, default=1)

    sub.add_parser("schema", help="print the JSON schema of Orders (for structured output)")
    sub.add_parser("map", help="list the provinces of the Europe 1500 map")

    serve = sub.add_parser("serve", help="play a nation yourself in the browser")
    serve.add_argument("--nation", default="france", help="the nation you rule")
    serve.add_argument("--seed", type=int, default=1)
    serve.add_argument("--turns", type=int, default=50)
    serve.add_argument("--bot", choices=sorted(BOTS), default="greedy", help="ruler of the others")
    serve.add_argument(
        "--player", action="append", default=[], metavar="NATION=BOT", help="override one ruler"
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    bench = sub.add_parser("bench", help="play many seeded games and count the winners")
    bench.add_argument("--games", type=int, default=20)
    bench.add_argument("--bot", choices=sorted(BOTS), default="greedy")
    bench.add_argument("--turns", type=int, default=50)
    return parser


# ---------------------------------------------------------------- play


def _players(state: GameState, default: str, overrides: list[str], seed: int) -> dict[str, Player]:
    players: dict[str, Player] = {n: BOTS[default](seed) for n in state.nations}
    for item in overrides:
        nation, _, bot = item.partition("=")
        if nation not in state.nations or bot not in BOTS:
            raise SystemExit(
                f"bad --player {item!r}: nations {sorted(state.nations)}, bots {sorted(BOTS)}"
            )
        players[nation] = BOTS[bot](seed)
    return players


def _play(args: argparse.Namespace) -> int:
    state = new_game(args.seed, max_turns=args.turns)
    players = _players(state, args.bot, args.player, args.seed)
    paint = _Painter(state)

    def narrate(turn: TurnRecord, _state: GameState) -> None:
        if args.quiet:
            return
        lines = [
            e.summary
            for e in turn.events
            if e.audience is None
            and (args.verbose or e.kind in HEADLINES)
            and not (
                e.kind == EventKind.PROVINCE_CAPTURED
                and not args.verbose
                and "independence" in e.summary
            )
        ]
        conquests = Counter(
            e.nations[0]
            for e in turn.events
            if e.kind == EventKind.PROVINCE_CAPTURED and "independence" in e.summary
        )
        for nation, n in sorted(conquests.items()):
            if not args.verbose:
                lines.append(f"{state.nations[nation].name} annexes {n} independent province(s)")
        for nation, error in turn.errors.items():
            lines.append(f"[{nation}'s ruler failed: {error}]")
        if lines:
            print(paint.dim(f"── {turn.year} · turn {turn.turn} ──"))
            for line in lines:
                print("  " + paint.names(line))

    record = asyncio.run(run_game(state, players, on_turn=narrate))
    _standings(record, paint)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(record.model_dump_json())
        print(f"\nsaved the game record to {args.save}")
    if args.html:
        from pax_agentica.viewer import render_html

        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(render_html(record))
        print(f"\nwrote the replay to {args.html}")
    return 0


def _standings(record: GameRecord, paint: "_Painter") -> None:
    final = record.turns[-1].after if record.turns else record.start
    names = {n: s.name for n, s in record.initial.nations.items()}
    rows = sorted(final.nations.items(), key=lambda kv: (-kv[1].score, kv[0]))
    print()
    print(
        f"{'':2}{'nation':<16}{'ruler':<8}{'prov':>5}{'score':>7}{'army':>6}{'ducats':>8}{'stab':>6}"
    )
    for nation, s in rows:
        mark = "👑" if nation == record.winner else ("☠ " if not s.alive else "  ")
        line = (
            f"{mark}{names[nation]:<16}{record.players[nation]:<8}{s.provinces:>5}"
            f"{s.score:>7}{s.regiments:>6}{s.resources.ducats:>8}{s.stability:>+6}"
        )
        print(paint.nation(nation, line) if s.alive else paint.dim(line))
    last = record.turns[-1].events if record.turns else []
    over = next((e for e in last if e.kind == EventKind.GAME_OVER), None)
    if over:
        print("\n" + paint.names(over.summary))


class _Painter:
    """ANSI colours in nation colours, unless NO_COLOR is set or stdout is not a terminal."""

    def __init__(self, state: GameState) -> None:
        self.on = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self.colors = {n.name: n.color for n in state.nations.values()}
        self.ids = {n.id: n.name for n in state.nations.values()}

    def _rgb(self, hex_color: str, text: str) -> str:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
        return f"\033[1;38;2;{r};{g};{b}m{text}\033[0m"

    def names(self, text: str) -> str:
        if not self.on:
            return text
        for name, color in sorted(self.colors.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(name, self._rgb(color, name))
        return text

    def nation(self, nation: str, text: str) -> str:
        return self._rgb(self.colors[self.ids[nation]], text) if self.on else text

    def dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.on else text


# ---------------------------------------------------------------- inspection


def _view(args: argparse.Namespace) -> int:
    state = new_game(args.seed)
    if args.nation not in state.nations:
        print(
            f"unknown nation {args.nation!r}; try one of {sorted(state.nations)}", file=sys.stderr
        )
        return 2
    print(view_for(state, args.nation).model_dump_json(indent=2))
    return 0


def _schema(_args: argparse.Namespace) -> int:
    print(json.dumps(Orders.model_json_schema(), indent=2))
    return 0


def _map(_args: argparse.Namespace) -> int:
    state = new_game(0)
    print(f"{'province':<16}{'owner':<10}{'terrain':<11}{'good':<7}{'dev':>4}  borders")
    for pid, definition in state.map.provinces.items():
        p = state.provinces[pid]
        borders = ", ".join(definition.neighbors)
        if definition.sea_neighbors:
            borders += " | by sea: " + ", ".join(definition.sea_neighbors)
        print(
            f"{pid:<16}{p.owner or '-':<10}{definition.terrain:<11}{definition.good:<7}"
            f"{p.development:>4}  {borders}"
        )
    return 0


def _serve(args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from pax_agentica.server import Session, create_app

    state = new_game(args.seed, max_turns=args.turns)
    if args.nation not in state.nations:
        print(
            f"unknown nation {args.nation!r}; try one of {sorted(state.nations)}", file=sys.stderr
        )
        return 2
    players = _players(state, args.bot, args.player, args.seed)
    players.pop(args.nation)
    app = create_app(Session(state, args.nation, players))
    url = f"http://{args.host}:{args.port}"
    print(f"You rule {state.nations[args.nation].name}. Open {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _bench(args: argparse.Namespace) -> int:
    wins: Counter[str] = Counter()
    lengths = []
    for seed in range(args.games):
        state = new_game(seed, max_turns=args.turns)
        players: dict[str, Player] = {n: BOTS[args.bot](seed) for n in state.nations}
        record = asyncio.run(run_game(state, players))
        wins[record.winner or "-"] += 1
        lengths.append(len(record.turns))
    print(f"{args.games} games, {args.bot} bots, average {sum(lengths) / len(lengths):.1f} turns")
    for nation, n in wins.most_common():
        print(f"  {nation:<10}{n:>4}  {n / args.games:>6.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
