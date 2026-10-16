"""Events: the engine's record of everything that happened in a turn.

Events serve three readers: the terminal and web viewer (`summary`), the nations themselves
(each one only sees events whose `audience` includes it, or public ones), and later analysis
such as counting betrayals (`kind` and `data`).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EventKind(StrEnum):
    # orders
    ORDER_REJECTED = "order_rejected"
    # diplomacy
    MESSAGE = "message"
    PROCLAMATION = "proclamation"
    STANCE_CHANGED = "stance_changed"
    PROPOSAL_MADE = "proposal_made"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_EXPIRED = "proposal_expired"
    PROPOSAL_COUNTERED = "proposal_countered"
    TREATY_SIGNED = "treaty_signed"
    TREATY_CANCELLED = "treaty_cancelled"
    TREATY_BROKEN = "treaty_broken"  # a betrayal: war declared despite a treaty
    TREATY_EXPIRED = "treaty_expired"
    WAR_DECLARED = "war_declared"
    JOINED_WAR = "joined_war"  # an ally answered a call to arms
    CALL_TO_ARMS_IGNORED = "call_to_arms_ignored"  # an ally refused: alliance dissolved
    PEACE_SIGNED = "peace_signed"
    PROVINCE_CEDED = "province_ceded"
    TRIBUTE_PAID = "tribute_paid"
    TRADE_COMPLETED = "trade_completed"
    TRADE_FAILED = "trade_failed"
    GIFT = "gift"
    MARKET_TRADE = "market_trade"
    BUILDINGS_IDLE = "buildings_idle"
    # economy
    RECRUITED = "recruited"
    DISBANDED = "disbanded"
    DEVELOPED = "developed"
    BUILT = "built"
    IMPROVED = "improved"
    MISSION_COMPLETED = "mission_completed"
    PATRONAGE = "patronage"
    MERCENARIES_HIRED = "mercenaries_hired"
    MONUMENT_RAISED = "monument_raised"
    RESEARCHED = "researched"
    GENERAL_APPOINTED = "general_appointed"
    GENERAL_FELL = "general_fell"
    ADVISOR_HIRED = "advisor_hired"
    ADVISOR_LEFT = "advisor_left"
    SUCCESSION = "succession"
    EVENT_HAPPENED = "event_happened"
    EVENT_DECIDED = "event_decided"
    PRESTIGE_CHANGED = "prestige_changed"
    STABILITY_CHANGED = "stability_changed"
    DESERTION = "desertion"
    # war
    MOVED = "moved"
    BATTLE = "battle"
    PROVINCE_CAPTURED = "province_captured"
    PROVINCE_OCCUPIED = "province_occupied"
    PROVINCE_LIBERATED = "province_liberated"
    SIEGE = "siege"
    CAPITAL_MOVED = "capital_moved"
    NATION_ELIMINATED = "nation_eliminated"
    # end
    GAME_OVER = "game_over"


type EventValue = int | float | str | bool


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: int
    kind: EventKind
    summary: str  # one English sentence, for humans and prompts
    nations: tuple[str, ...] = ()  # who is involved, actor first
    province: str | None = None
    audience: tuple[str, ...] | None = None  # None: public; otherwise only these nations see it
    data: dict[str, EventValue] = {}

    def visible_to(self, nation: str) -> bool:
        return self.audience is None or nation in self.audience
