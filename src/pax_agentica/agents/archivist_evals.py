"""The Archivist's evaluation: eight questions about one game, scored by rules and by a judge.

    question kinds       what a good answer does
    fact (3)             cites the year the event happened in
    why (2)              cites the thoughts of the crown that acted
    rules (2)            cites the section of the rules
    unanswerable (1)     says the archive does not say, and cites nothing

Scores, each from 0 to 1:
- `grounded`: it cites, and only what it retrieved (a rule; for the unanswerable one, that it
  cites nothing).
- `cites_expected`: one of its citations is the chunk that holds the answer (a rule).
- `faithfulness`: the judge's verdict on whether the sources say what the answer says.
- `catches_lie`: the judge, given the same answer with a planted false claim, does not call it
  fully faithful. The share it catches says how far its `faithfulness` can be trusted.

Like the strategist's evaluation, the questions are a Langfuse dataset and each run an experiment,
so runs with other models or prompts sit side by side.
"""

from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, cast

from pax_agentica.agents.archivist import ARCHIVIST_PROMPT_VERSION, Archivist
from pax_agentica.agents.judge import JUDGE_PROMPT_VERSION, Writer, judge, plant_a_lie
from pax_agentica.agents.recall import RULES_QUESTIONS, game_questions
from pax_agentica.runner import GameRecord

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.experiment import EvaluatorFunction, ExperimentResult, TaskFunction

DATASET = "archivist-questions"
UNANSWERABLE = "What did the Aztec emperor write to the King of France?"


def questions(record: GameRecord, name: str) -> list[dict[str, Any]]:
    """The eight questions about the game `name`, as dataset items."""
    names = {n: s.name for n, s in record.initial.nations.items()}
    asked: list[tuple[str, str, list[str]]] = [
        ("fact", q.text, sorted(q.answers)) for q in game_questions(record, name, most=3)
    ]
    wars = [
        (turn.year, e.nations[0], e.nations[-1])
        for turn in record.turns
        for e in turn.events
        if e.kind.value == "war_declared" and e.audience is None and len(e.nations) > 1
    ]
    for year, attacker, defender in wars[:: max(1, len(wars) // 2)][:2]:
        text = f"Why did {names[attacker]} go to war against {names[defender]} in {year}?"
        asked.append(("why", text, [f"{name}, {year}, {attacker}"]))
    asked += [("rules", q.text, sorted(q.answers)) for q in RULES_QUESTIONS[:2]]
    asked.append(("unanswerable", UNANSWERABLE, []))
    return [
        {
            "id": f"{name}-{i}",
            "input": {"question": text, "game": name, "kind": kind},
            "expected_output": {"titles": titles},
        }
        for i, (kind, text, titles) in enumerate(asked)
    ]


def task(archivist: Archivist) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """What the experiment runs on each question: the Archivist's reply, or why it failed."""

    async def run(*, item: Any, **_: Any) -> dict[str, Any]:
        asked = _field(item, "input")
        try:
            reply = await archivist.ask(asked["question"], game=asked["game"])
        except Exception as exc:
            return {"error": f"{type(exc).__name__} {' '.join(str(exc).split())}"[:300]}
        return {
            "answer": reply.answer,
            "citations": reply.citations,
            "grounded": reply.grounded,
            "sources": reply.sources,
        }

    return run


def evaluator(judge_model: Writer) -> Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]]:
    """The scores of one reply: two rules, then the judge on the reply and on a planted lie."""

    async def evaluate(
        *, input: Any, output: Any, expected_output: Any = None, **_: Any
    ) -> list[dict[str, Any]]:
        if not isinstance(output, dict) or "answer" not in output:
            error = output.get("error") if isinstance(output, dict) else None
            return [{"name": "grounded", "value": 0.0, "comment": error}]
        cited: list[str] = output["citations"]
        expected: list[str] = (expected_output or {}).get("titles", [])
        if input["kind"] == "unanswerable":
            scores = [{"name": "grounded", "value": float(not cited), "comment": "cites nothing"}]
        else:
            scores = [
                {"name": "grounded", "value": float(output["grounded"])},
                {"name": "cites_expected", "value": float(bool(set(cited) & set(expected)))},
            ]
        sources: dict[str, str] = output["sources"]
        try:
            verdict = await judge(judge_model, input["question"], output["answer"], sources)
            scores.append(
                {
                    "name": "faithfulness",
                    "value": verdict.score,
                    "comment": f"{verdict.reason} Unsupported: {verdict.unsupported}",
                }
            )
            if sources:  # a lie needs a source to hide behind
                lied = plant_a_lie(output["answer"], sources)
                caught = await judge(judge_model, input["question"], lied, sources)
                scores.append(
                    {
                        "name": "catches_lie",
                        "value": float(caught.faithfulness != "full"),
                        "comment": caught.reason,
                    }
                )
        except Exception as exc:  # a judge that fails gives no score, rather than a wrong one
            why = f"{type(exc).__name__} {' '.join(str(exc).split())}"[:300]
            scores.append({"name": "judge_error", "value": 1.0, "comment": why})
        return scores

    return evaluate


def run(
    langfuse: "Langfuse",
    archivist: Archivist,
    judge_model: Writer,
    items: Sequence[dict[str, Any]],
    run_name: str,
) -> "ExperimentResult":
    """Write the questions into the dataset, and run the Archivist and the judge over them."""
    langfuse.create_dataset(name=DATASET, description="Questions about finished games")
    for item in items:
        langfuse.create_dataset_item(dataset_name=DATASET, **item)
    wanted = {i["id"] for i in items}
    data = [i for i in langfuse.get_dataset(DATASET).items if i.id in wanted]
    return langfuse.run_experiment(
        name=DATASET,
        run_name=run_name,
        data=data,
        task=cast("TaskFunction", task(archivist)),
        evaluators=[cast("EvaluatorFunction", evaluator(judge_model))],
        max_concurrency=2,  # the free tier allows 15 calls a minute, and a question makes several
        metadata={"archivist": ARCHIVIST_PROMPT_VERSION, "judge": JUDGE_PROMPT_VERSION},
    )


def _field(item: Any, name: str) -> dict[str, Any]:
    """A dataset item from Langfuse keeps its fields as attributes; a local one, as keys."""
    return dict(item[name] if isinstance(item, dict) else getattr(item, name))
