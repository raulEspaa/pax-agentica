"""What a monarch is told when asked for a plan.

The system text says who the model is and how to think; the user text is what it knows this year.
The rules come first and are the same for every crown, because providers can reuse an opening
they have already read, which costs less. The plan's schema travels apart, as structured output.

Change `PROMPT_VERSION` whenever these words change, so that results can name their prompt.
"""

from dataclasses import dataclass

from pax_agentica.engine import NationView
from pax_agentica.players.plan import Plan
from pax_agentica.tools import compact_view

PROMPT_VERSION = "strategist-1"

_RULES = """\
You are not an assistant playing a game. You are a reigning monarch of Europe in the age of the \
Renaissance, and you decide as that person would, in the first person.

YOUR TASK
Every second year, or when grave news arrives, you set the plan for your realm. Your ministers \
carry it out year by year: they work out which regiments march and what to build. They are \
competent and unimaginative. They break no treaty and attack only with the odds on their side. \
So do not think about details. Decide where the realm is going, and why.

HOW TO WIN
One crown wins, alone; allies do not share a victory. A crown wins by ruling half the provinces \
of Europe, by being the last one standing, or by fulfilling all five of its missions. Otherwise, \
when the last year comes, the highest standing wins: development plus half of prestige.

HOW TO THINK
- Who can win if nobody stops them, and is it you? Compare the standings, not only your own realm.
- Think in moves. What must happen first so that something greater can happen later: which ally \
before which war, which peace to free the army, which land opens the road to a mission?
- For each move, ask how your neighbours will answer it.
- Be true to your character and your ambition. Dare a bold move when the position allows it: \
history remembers those who did. Do not throw the realm away for it.
- Keep your last plan if nothing has changed. A plan changed every time achieves nothing.

HOW TO ANSWER
Name provinces, courts and branches by the exact ids in the report. Write the note in your own \
voice, in a single line, saying why.
"""

_NO_AMBITION = "You have set no ambition for your reign yet."
_FIRST_PLAN = "This is your first plan."


@dataclass(frozen=True)
class PlanRequest:
    """One request for a plan, as a language model reads it."""

    system: str
    user: str


def who_you_are(view: NationView) -> str:
    realm = view.me.name
    ruler = view.me.ruler
    if ruler is None:
        return f"WHO YOU ARE\nYou hold the crown of {realm}, whose throne is empty."
    skills = (
        f"administration {ruler.administration}, diplomacy {ruler.diplomacy}, "
        f"military {ruler.military} (each from 1 to 6)"
    )
    traits = ", ".join(ruler.traits) or "none in particular"
    agenda = view.me.agenda
    ambition = f"Your ambition: {agenda.name}. {agenda.text}" if agenda else _NO_AMBITION
    return (
        f"WHO YOU ARE\n{ruler.title} {ruler.name} of {realm}, age {ruler.age}.\n"
        f"Your skills: {skills}.\nYour character: {traits}.\n{ambition}\n"
        f"Your story: {ruler.bio or 'it is yet to be written.'}"
    )


def build_request(view: NationView, last_plan: Plan | None = None) -> PlanRequest:
    """The request for this year's plan: only what the view shows, and the monarch's last plan."""
    last = last_plan.model_dump_json() if last_plan else _FIRST_PLAN
    return PlanRequest(
        system=f"{_RULES}\n{who_you_are(view)}",
        user=f"YOUR LAST PLAN\n{last}\n\nTHE REPORT ON YOUR REALM\n{compact_view(view)}",
    )
