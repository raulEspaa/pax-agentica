"""The checks a plan passes before anyone acts on it: the AI proposes, the code decides."""

from pax_agentica.engine import NationView
from pax_agentica.players.plan import Plan


def clean_plan(plan: Plan, view: NationView) -> tuple[Plan, list[str]]:
    """The plan without what names nothing real, and a line for each thing dropped.

    `view.nations` holds the other courts, so the realm itself is dropped as enemy or friend.
    """
    provinces = {p.id for p in view.provinces}
    courts = {n.id for n in view.nations if n.alive}
    dropped: list[str] = []

    def keep(field: str, names: list[str], real: set[str]) -> list[str]:
        dropped.extend(f"{field} {name}" for name in names if name not in real)
        return [name for name in names if name in real]

    war_on = plan.war_on if plan.war_on in courts else None
    if plan.war_on is not None and war_on is None:
        dropped.append(f"war_on {plan.war_on}")
    cleaned = plan.model_copy(
        update={
            "conquer": keep("conquer", plan.conquer, provinces),
            "war_on": war_on,
            "peace_with": keep("peace_with", plan.peace_with, courts),
            "befriend": keep("befriend", plan.befriend, courts),
        }
    )
    return cleaned, dropped
