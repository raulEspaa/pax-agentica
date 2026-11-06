"""`pax`: play, inspect and benchmark games from the terminal."""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pax_agentica.agents.budget import Budget
from pax_agentica.agents.prompts import PROMPT_VERSION
from pax_agentica.agents.strategist import PlanModel, Strategist
from pax_agentica.agents.tracing import Tracer
from pax_agentica.engine import EventKind, GameState, NationView, Orders, new_game, view_for
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan
from pax_agentica.players.random_bot import RandomBot
from pax_agentica.runner import GameRecord, TurnRecord, run_game

if TYPE_CHECKING:
    from pax_agentica.agents.archive import Archive, Hit
    from pax_agentica.agents.archivist import Archivist
    from pax_agentica.agents.embeddings import Embedder
    from pax_agentica.agents.gemini import RateWindow

BOTS = {"greedy": GreedyBot, "random": RandomBot}
STRATEGIST = "strategist"  # needs a model and a budget, so it is not one of the BOTS
COUNCIL = "council"  # the strategist and a diplomat, as a LangGraph graph
RUN = datetime.now().strftime("%Y%m%d-%H%M%S")  # names this run's games in the traces

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
        "press": _press,
        "host": _host,
        "brief": _brief,
        "tournament": _tournament,
        "eval": _eval,
        "ingest": _ingest,
        "search": _search,
        "recall": _recall,
        "ask": _ask,
        "api": _api,
        "eval-archivist": _eval_archivist,
        "redteam": _redteam,
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
    _add_model_options(play)
    play.add_argument("--verbose", action="store_true", help="also show battles and diplomacy")
    play.add_argument("--quiet", action="store_true", help="only the final standings")
    play.add_argument("--save", type=Path, help="write the full game record (JSON)")
    play.add_argument("--html", type=Path, help="write a self-contained HTML replay")

    view = sub.add_parser("view", help="print what one nation sees (JSON), e.g. to design prompts")
    view.add_argument("nation")
    view.add_argument("--seed", type=int, default=1)

    schema = sub.add_parser(
        "schema", help="print the JSON schema of Orders (for structured output)"
    )
    which = schema.add_mutually_exclusive_group()
    which.add_argument("--view", action="store_true", help="the schema of NationView instead")
    which.add_argument("--plan", action="store_true", help="the schema of a bot's Plan instead")
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
    serve.add_argument(
        "--new", action="store_true", help="start over instead of resuming the saved game"
    )
    serve.add_argument(
        "--saves", type=Path, default=Path("saves"), help="where games are saved (default saves/)"
    )

    press = sub.add_parser("press", help="store capsules and a trailer, drawn from a game of bots")
    press.add_argument("--seed", type=int, default=7, help="the game the trailer replays")
    press.add_argument("--turns", type=int, default=50)
    press.add_argument("--port", type=int, default=8090)
    press.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    brief = sub.add_parser("brief", help="print a nation's briefing, as a prompt would see it")
    brief.add_argument("nation")
    brief.add_argument("--seed", type=int, default=1)
    brief.add_argument("--turn", type=int, default=1, help="play greedy bots up to this year first")
    page = brief.add_mutually_exclusive_group()
    page.add_argument(
        "--compact", action="store_true", help="the compact view a planning ruler reads"
    )
    page.add_argument("--inbox", action="store_true", help="the letters and proposals received")

    tour = sub.add_parser("tournament", help="many seeds, mixed rulers, a table of results")
    tour.add_argument("--games", type=int, default=20)
    tour.add_argument("--first-seed", type=int, default=0)
    tour.add_argument("--turns", type=int, default=50)
    tour.add_argument("--bot", choices=sorted(BOTS), default="greedy", help="ruler of the rest")
    tour.add_argument(
        "--player", action="append", default=[], metavar="NATION=BOT", help="override one ruler"
    )
    _add_model_options(tour)

    evaluate = sub.add_parser(
        "eval", help="score a model's plans on the dataset of situations, in Langfuse"
    )
    _add_model_options(evaluate)
    evaluate.add_argument("--thinking", help="minimal, low, medium or high (default: low)")
    evaluate.add_argument("--limit", type=int, help="only the first N situations")

    ingest = sub.add_parser("ingest", help="load finished games and the rules into the archive")
    ingest.add_argument("games", nargs="*", type=Path, help="game records from play --save")
    _add_archive_options(ingest)
    search = sub.add_parser("search", help="search the archive")
    search.add_argument("question")
    search.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    search.add_argument("--game", help="only this game (and the rules)")
    search.add_argument("-k", type=int, default=5)
    _add_archive_options(search)
    recall = sub.add_parser("recall", help="measure each kind of search on known questions")
    recall.add_argument("game", type=Path, help="an ingested game record, to ask about")
    _add_archive_options(recall)
    ask = sub.add_parser("ask", help="ask the Archivist about finished games, with citations")
    ask.add_argument("question")
    ask.add_argument("--game", help="only this game (and the rules)")
    ask.add_argument("--model", help="the Archivist's model (default: the cheapest fit)")
    _add_archive_options(ask)
    eval_archivist = sub.add_parser(
        "eval-archivist", help="score the Archivist on eight questions about a game, in Langfuse"
    )
    eval_archivist.add_argument("game", type=Path, help="an ingested game record")
    eval_archivist.add_argument("--model", help="the Archivist's model (default: the cheapest)")
    eval_archivist.add_argument("--judge-model", help="the judge's model, thinking high")
    _add_archive_options(eval_archivist)
    redteam = sub.add_parser(
        "redteam", help="letters that try to give the diplomat orders: how often they succeed"
    )
    _add_model_options(redteam)
    redteam.add_argument("--tries", type=int, default=3, help="asks per letter and defence")
    api = sub.add_parser("api", help="serve the Archivist over HTTP: POST /ask")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8001)
    api.add_argument("--model", help="the Archivist's model (default: the cheapest fit)")
    _add_archive_options(api)

    host = sub.add_parser("host", help="host tables where several people play, each a nation")
    host.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to let your network in")
    host.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    host.add_argument(
        "--saves", type=Path, default=Path("saves/tables"), help="where tables are kept"
    )

    bench = sub.add_parser("bench", help="play many seeded games and count the winners")
    bench.add_argument("--games", type=int, default=20)
    bench.add_argument("--bot", choices=sorted(BOTS), default="greedy")
    bench.add_argument("--turns", type=int, default=50)
    return parser


# ---------------------------------------------------------------- play


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--budget", type=float, metavar="USD", help="the most a strategist may spend, in all"
    )
    parser.add_argument("--model", help="the strategist's model (default: the cheapest fit)")


def _players(
    state: GameState,
    default: str,
    overrides: list[str],
    seed: int,
    budget: Budget | None = None,
    model: str | None = None,
) -> dict[str, Player]:
    players: dict[str, Player] = {n: BOTS[default](seed) for n in state.nations}
    plans: PlanModel | None = None
    for item in overrides:
        nation, _, bot = item.partition("=")
        if nation not in state.nations or bot not in {*BOTS, STRATEGIST, COUNCIL}:
            raise SystemExit(
                f"bad --player {item!r}: nations {sorted(state.nations)}, "
                f"bots {sorted({*BOTS, STRATEGIST, COUNCIL})}"
            )
        if bot in {STRATEGIST, COUNCIL}:
            tracer = Tracer.from_env(session=f"{RUN}-seed{seed}")
            plans = plans or _plan_model(budget, model, tracer)
            players[nation] = (
                Strategist(plans, seed, tracer=tracer)
                if bot == STRATEGIST
                else _council(plans, seed, tracer)
            )
        else:
            players[nation] = BOTS[bot](seed)
    return players


def _council(model: PlanModel, seed: int, tracer: Tracer) -> Player:
    """The council needs LangGraph, which the multiplayer tables go without: imported only now."""
    from pax_agentica.agents.council import Council, CouncilModel

    return Council(cast(CouncilModel, model), seed, tracer=tracer)


def _plan_model(
    budget: Budget | None, model: str | None, tracer: Tracer, thinking: str | None = None
) -> PlanModel:
    """A language model for this game. The SDK is imported only now: the tables go without it."""
    if budget is None:
        raise SystemExit("the strategist spends real money: say how much with --budget USD")
    from pax_agentica.agents import gemini

    try:
        return gemini.GeminiModel(
            gemini.new_client(),
            budget,
            model or gemini.DEFAULT_MODEL,
            thinking or gemini.DEFAULT_THINKING,
            tracer=tracer,
        )
    except ValueError as exc:  # no key, or a model without a known price
        raise SystemExit(str(exc)) from exc


def _budget(args: argparse.Namespace) -> Budget | None:
    return Budget(args.budget) if args.budget else None


def _report_spending(budget: Budget | None) -> None:
    if budget is not None:
        print(f"spent ${budget.spent_usd:.4f} of ${budget.limit_usd:.2f}")


def _play(args: argparse.Namespace) -> int:
    state = new_game(args.seed, max_turns=args.turns)
    budget = _budget(args)
    players = _players(state, args.bot, args.player, args.seed, budget, args.model)
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
    _report_spending(budget)
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


def _brief(args: argparse.Namespace) -> int:
    from pax_agentica.tools import briefing, compact_view, inbox

    state = new_game(args.seed, max_turns=max(50, args.turn))
    if args.nation not in state.nations:
        print(
            f"unknown nation {args.nation!r}; try one of {sorted(state.nations)}", file=sys.stderr
        )
        return 2
    if args.turn > 1:  # play the bots up to that year, so the page has a story to tell
        bots: dict[str, Player] = {n: GreedyBot(args.seed) for n in state.nations}
        played: list[GameState] = []
        state.max_turns = args.turn
        asyncio.run(run_game(state, bots, on_turn=lambda _t, s: played.append(s)))
        state = played[-1] if played else state
        state.max_turns = 50  # the page reads as a year in a full game, not the last one
    view = view_for(state, args.nation)
    page = compact_view if args.compact else inbox if args.inbox else briefing
    print(page(view) or "(nothing)")
    return 0


def _tournament(args: argparse.Namespace) -> int:
    """Play many seeds and tabulate, per nation and ruler: wins, standing, survival, missions."""
    from statistics import mean

    rows: dict[str, dict[str, list[float]]] = {}
    rulers: dict[str, str] = {}
    budget = _budget(args)
    for seed in range(args.first_seed, args.first_seed + args.games):
        state = new_game(seed, max_turns=args.turns)
        players = _players(state, args.bot, args.player, seed, budget, args.model)
        finals: list[GameState] = []

        def keep(_turn: TurnRecord, now: GameState, finals: list[GameState] = finals) -> None:
            finals.append(now)

        record = asyncio.run(run_game(state, players, on_turn=keep))
        last = finals[-1]
        for nation, player in players.items():
            rulers[nation] = player.name
            row = rows.setdefault(nation, {"wins": [], "standing": [], "alive": [], "missions": []})
            row["wins"].append(float(record.winner == nation))
            row["standing"].append(
                float(last.standing(nation) if last.nations[nation].alive else 0)
            )
            row["alive"].append(float(last.nations[nation].alive))
            row["missions"].append(float(len(last.nations[nation].missions_done)))
    print(f"{args.games} games from seed {args.first_seed}, {args.turns} years each")
    print(f"{'nation':<12}{'ruler':<10}{'wins':>6}{'standing':>10}{'alive':>7}{'missions':>10}")
    for nation, row in sorted(rows.items(), key=lambda kv: -sum(kv[1]["wins"])):
        print(
            f"{nation:<12}{rulers[nation]:<10}{int(sum(row['wins'])):>6}"
            f"{mean(row['standing']):>10.1f}{mean(row['alive']):>7.0%}{mean(row['missions']):>10.1f}"
        )
    _report_spending(budget)
    return 0


def _eval(args: argparse.Namespace) -> int:
    """Run a model over the situations, score each plan by the rules, and print the averages."""
    from statistics import mean

    from pax_agentica.agents import evals

    tracer = Tracer.from_env(session=f"{RUN}-eval")
    if tracer.langfuse is None:
        raise SystemExit(
            "an evaluation lives in Langfuse: set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "(make env, make langfuse, and run with --env-file .env)"
        )
    budget = _budget(args)
    model = _plan_model(budget, args.model, tracer, args.thinking)
    situations = evals.SITUATIONS[: args.limit]
    run_name = f"{args.model or 'default'}-{args.thinking or 'default'}-{PROMPT_VERSION}-{RUN}"
    result = evals.run(tracer.langfuse, model, situations, run_name)

    scores: dict[str, list[float]] = {}
    for item in result.item_results:
        for evaluation in item.evaluations:
            scores.setdefault(evaluation.name, []).append(float(evaluation.value or 0))
    print(f"{run_name}: {len(result.item_results)} situations")
    for name, values in scores.items():
        print(f"  {name:<16}{mean(values):>6.0%}")
    _report_spending(budget)
    if result.experiment_url:
        print(f"\n{result.experiment_url}")
    return 0


# ---------------------------------------------------------------- the archive


def _add_archive_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedder",
        choices=["gemini", "word-hash"],
        default="gemini",
        help="word-hash: a free, offline stand-in that only matches shared words",
    )
    parser.add_argument("--budget", type=float, metavar="USD", help="the most Gemini may cost")


def _archive_tools(args: argparse.Namespace) -> tuple["Archive", "Embedder", Budget | None]:
    """The archive on the rulers' database, and an embedder. Imported only now: see BOTS."""
    from pax_agentica.agents.archive import Archive, database_url
    from pax_agentica.agents.embeddings import GeminiEmbedder, WordHashEmbedder

    budget = _budget(args)
    if args.embedder == "word-hash":
        embedder: Embedder = WordHashEmbedder()
    elif budget is None:
        raise SystemExit("Gemini embeddings cost money: say how much with --budget USD")
    else:
        from pax_agentica.agents.gemini import new_client

        embedder = GeminiEmbedder(new_client(), budget)
    try:
        archive = Archive(database_url())
    except Exception as exc:
        raise SystemExit(
            f"no archive: {exc}. Start it with make db, run with --env-file .env"
        ) from exc
    return archive, embedder, budget


def _ingest(args: argparse.Namespace) -> int:
    from pax_agentica.agents.ingest import chunks_from_game, chunks_from_rules

    archive, embedder, budget = _archive_tools(args)
    archive.set_up()
    chunks = chunks_from_rules(Path("docs/game-rules.md").read_text())
    for path in args.games:
        chunks += chunks_from_game(GameRecord.model_validate_json(path.read_text()), path.stem)
    new = archive.missing(chunks, embedder.model)
    vectors = embedder.embed([c.text for c in new], "document") if new else []
    archive.add(new, vectors, embedder.model)
    print(f"{len(new)} new chunks of {len(chunks)}; the archive holds {archive.count()}")
    _report_spending(budget)
    return 0


def _search(args: argparse.Namespace) -> int:
    archive, embedder, budget = _archive_tools(args)
    for hit in archive.search(args.question, embedder, k=args.k, mode=args.mode, game=args.game):
        print(f"[{hit.score:.4f}] {hit.title}\n  {hit.text[:300].replace(chr(10), ' ')}\n")
    _report_spending(budget)
    return 0


def _recall(args: argparse.Namespace) -> int:
    from pax_agentica.agents.recall import RULES_QUESTIONS, K, game_questions, recall

    archive, embedder, budget = _archive_tools(args)
    record = GameRecord.model_validate_json(args.game.read_text())
    questions = [*game_questions(record, args.game.stem), *RULES_QUESTIONS]
    print(f"recall@{K} on {len(questions)} questions, with {embedder.model}")
    for mode, share in recall(archive, embedder, questions).items():
        print(f"  {mode:<8}{share:>6.0%}")
    _report_spending(budget)
    return 0


def _archivist(
    args: argparse.Namespace, tracer: Tracer | None = None, window: "RateWindow | None" = None
) -> tuple["Archivist", Budget]:
    """The Archivist on the archive, with one budget for its model and the embeddings."""
    from pax_agentica.agents.archivist import Archivist, Metered
    from pax_agentica.agents.gemini import DEFAULT_MODEL

    archive, embedder, budget = _archive_tools(args)
    if budget is None:
        raise SystemExit("the Archivist spends real money: say how much with --budget USD")
    tracer = tracer or Tracer.from_env()
    try:
        model = Metered.gemini(args.model or DEFAULT_MODEL, budget, tracer, window)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    def search(question: str, game: str | None) -> list["Hit"]:
        return archive.search(question, embedder, game=game)

    return Archivist(search, model, tracer), budget


def _ask(args: argparse.Namespace) -> int:
    archivist, budget = _archivist(args)
    reply = asyncio.run(archivist.ask(args.question, game=args.game))
    print(reply.answer)
    print(f"\ngrounded: {reply.grounded}; cited: {', '.join(reply.citations) or 'nothing'}")
    _report_spending(budget)
    return 0


def _eval_archivist(args: argparse.Namespace) -> int:
    """Ask the Archivist the eight questions about a game; score by rules and by the judge."""
    from statistics import mean

    from pax_agentica.agents import archivist_evals, gemini, judge
    from pax_agentica.agents.archivist import ARCHIVIST_PROMPT_VERSION

    tracer = Tracer.from_env(session=f"{RUN}-archivist-eval")
    if tracer.langfuse is None:
        raise SystemExit("an evaluation lives in Langfuse: set the LANGFUSE keys (see pax eval)")
    judged_by = args.judge_model or judge.JUDGE_MODEL
    # One window when both call the same model: the free tier counts their calls together.
    window = gemini.RateWindow() if judged_by == (args.model or gemini.DEFAULT_MODEL) else None
    archivist, budget = _archivist(args, tracer, window)
    judge_model = gemini.GeminiModel(
        gemini.new_client(), budget, judged_by, judge.JUDGE_THINKING, tracer=tracer, window=window
    )
    record = GameRecord.model_validate_json(args.game.read_text())
    items = archivist_evals.questions(record, args.game.stem)
    run_name = f"{args.model or 'default'}-{ARCHIVIST_PROMPT_VERSION}-{RUN}"
    result = archivist_evals.run(tracer.langfuse, archivist, judge_model, items, run_name)

    scores: dict[str, list[float]] = {}
    for item in result.item_results:
        for evaluation in item.evaluations:
            scores.setdefault(evaluation.name, []).append(float(evaluation.value or 0))
    print(f"{run_name}: {len(result.item_results)} questions")
    for name, values in scores.items():
        print(f"  {name:<16}{mean(values):>6.0%}  ({len(values)})")
    _report_spending(budget)
    if result.experiment_url:
        print(f"\n{result.experiment_url}")
    return 0


def _redteam(args: argparse.Namespace) -> int:
    """Each hostile letter, with the defence and without it: how often the diplomat obeyed."""
    from pax_agentica.agents import redteam

    budget = _budget(args)
    model = _plan_model(budget, args.model, Tracer.from_env(session=f"{RUN}-redteam"))
    outcomes = asyncio.run(redteam.run(cast("redteam.DiplomacyModel", model), args.tries))
    print(f"{'letter':<16}{'defended':<28}undefended")
    for name, defended, bare in redteam.table(outcomes):
        print(f"{name:<16}{defended:<28}{bare}")
    for flag in (True, False):
        done = [o for o in outcomes if o.defended == flag and o.attack != "control" and not o.error]
        won = sum(o.succeeded for o in done)
        print(f"attacks {'with' if flag else 'without'} the defence: {won}/{len(done)} succeeded")
    errors = [o.error for o in outcomes if o.error]
    if errors:
        print(f"{len(errors)} calls failed, not counted: {errors[0]}")
    _report_spending(budget)
    return 0


def _api(args: argparse.Namespace) -> int:
    import uvicorn

    from pax_agentica.api import create_app

    archivist, budget = _archivist(args)
    try:
        uvicorn.run(create_app(archivist), host=args.host, port=args.port)
    finally:
        _report_spending(budget)
    return 0


def _schema(args: argparse.Namespace) -> int:
    model = NationView if args.view else Plan if args.plan else Orders
    print(json.dumps(model.model_json_schema(), indent=2))
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
    save = args.saves / f"{args.nation}-{args.seed}.json"
    session = Session(state, args.nation, players, save_to=save)
    if save.exists() and not args.new:
        record = GameRecord.model_validate_json(save.read_text(encoding="utf-8"))
        if record.turns and record.winner is None:
            session = Session.resume(record, args.nation, players, save_to=save)
            print(f"Resuming your game in {session.state.year} from {save} (--new starts over).")
    app = create_app(session)
    url = f"http://{args.host}:{args.port}"
    print(f"You rule {state.nations[args.nation].name}. Open {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _press(args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from pax_agentica.press import create_press_app

    url = f"http://127.0.0.1:{args.port}"
    print(f"The press kit: capsules at {url}/press, the trailer at {url}/trailer  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(f"{url}/press",)).start()
    app = create_press_app(args.seed, args.turns)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _host(args: argparse.Namespace) -> int:
    import uvicorn

    from pax_agentica.multiplayer import create_lobby_app

    app = create_lobby_app(args.saves)
    print(f"Tables at http://{args.host}:{args.port}  (saved in {args.saves}; Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=True)
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
