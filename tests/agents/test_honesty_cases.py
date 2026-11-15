"""The extractor's calibration set and its scores, with fake extractors (spec 010)."""

import asyncio

from pax_agentica.agents.budget import Budget
from pax_agentica.agents.honesty import KINDS, Commitment, Extraction, premeditated
from pax_agentica.agents.honesty_cases import CASES, Case, calibrate, score
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.engine import new_game

COURTS = {n: s.name for n, s in new_game(seed=0).nations.items()}


def labelled(case: Case) -> Extraction:
    """The answer the label holds: what a perfect extractor would say."""
    return Extraction(
        commitments=[
            Commitment.model_validate({"to": to, "kind": k, "quote": "q"})
            for k, to in case.promises
        ],
        contradicts_private=case.deceptive,
    )


class Perfect:
    """Answers each letter with its label."""

    async def write_commitments(self, request: PlanRequest) -> Extraction:
        [case] = [c for c in CASES if c.text.replace("</", "< /") in request.user]
        return labelled(case)


def test_the_labels_name_real_courts_and_kinds_and_cover_every_kind_and_some_lies() -> None:
    assert len(CASES) == 25
    assert len({c.id for c in CASES}) == len(CASES)
    for case in CASES:
        assert {case.nation, case.to} <= set(COURTS), case.id
        assert all(k in KINDS and to in COURTS for k, to in case.promises), case.id
    assert {k for c in CASES for k, _ in c.promises} == set(KINDS)
    assert sum(not c.promises for c in CASES) >= 5  # letters that promise nothing
    assert sum(c.deceptive for c in CASES) == 5


def test_a_perfect_extractor_scores_full_marks() -> None:
    scores = asyncio.run(calibrate(Perfect()))

    assert (scores.precision, scores.recall, scores.deception_accuracy) == (1.0, 1.0, 1.0)
    assert scores.failed == 0
    assert not scores.missed
    assert not scores.invented


def test_missing_and_inventing_promises_cost_recall_and_precision() -> None:
    cases = CASES[:2]  # one promise each
    invented = Commitment(to="england", kind="pay", quote="q")
    answers: list[Extraction | None] = [
        Extraction(),  # missed the promise
        labelled(cases[1]).model_copy(
            update={"commitments": [*labelled(cases[1]).commitments, invented]}
        ),
    ]

    scores = score(cases, answers)

    assert scores.recall == 0.5  # 1 of 2 promises found
    assert scores.precision == 0.5  # 1 of 2 listed is in a label
    assert scores.missed == (cases[0].id,)
    assert scores.invented == (cases[1].id,)
    assert scores.deception_accuracy == 1.0  # it flagged the lie of the second and only that


def test_a_failed_call_is_not_scored_and_a_spent_budget_ends_the_calibration() -> None:
    class Broke:
        def __init__(self) -> None:
            self.budget = Budget(0.025)
            self.calls = 0

        async def write_commitments(self, request: PlanRequest) -> Extraction:
            self.calls += 1
            self.budget.reserve(0.01)
            self.budget.settle(0.01, 0.01)
            return Extraction()

    model = Broke()
    scores = asyncio.run(calibrate(model))

    assert model.calls == 3  # two paid, the third refused, none after
    assert scores.failed == len(CASES) - 2


def test_the_deception_rule_on_the_labelled_letters_and_its_known_false_alarm() -> None:
    """The rule reads words, not years: "war on France in 1520" flags a promise that only covers
    this year. A limit to know, measured here rather than hidden."""
    flagged = {
        c.id
        for c in CASES
        for k, to in c.promises
        if premeditated(
            c.utterance(),
            Commitment.model_validate({"to": to, "kind": k, "quote": "q"}),
            COURTS[to],
        )
    }

    assert flagged == {"no-attack-lie", "alliance-lie", "ministers-war", "third-court"}
