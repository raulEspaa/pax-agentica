"""The Archivist over HTTP: ask about finished games, get an answer with citations.

    uv run --env-file .env pax api --budget 0.20     # then POST http://127.0.0.1:8001/ask

A separate app from `server.py` on purpose: the public tables image goes without the AI libraries
and without a key that spends money. The whole process shares one budget; once it is spent every
question gets a 503 until a restart, so a public endpoint cannot run up a bill.
"""

from fastapi import FastAPI, HTTPException
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from pydantic import BaseModel, Field

from pax_agentica.agents.archivist import Archivist
from pax_agentica.agents.budget import BudgetExceeded


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    session: str | None = Field(None, description="from the last answer, to follow on from it")
    game: str | None = Field(None, description="keep to one game (and the rules), e.g. seed1")


class Answer(BaseModel):
    answer: str
    citations: list[str]
    grounded: bool = Field(description="it cited something, and only what it retrieved")
    session: str


def create_app(archivist: Archivist) -> FastAPI:
    app = FastAPI(title="Pax Agentica: the Archivist")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask")
    async def ask(question: Question) -> Answer:
        try:
            reply = await archivist.ask(question.question, question.session, question.game)
        except BudgetExceeded as exc:
            raise HTTPException(503, "the Archivist's budget is spent") from exc
        except LlmCallsLimitExceededError as exc:
            raise HTTPException(
                422, "the question took too many searches: ask something narrower"
            ) from exc
        return Answer(
            answer=reply.answer,
            citations=reply.citations,
            grounded=reply.grounded,
            session=reply.session,
        )

    return app
