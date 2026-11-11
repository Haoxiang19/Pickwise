"""Sessions (in memory). Orders in SQLite are added with the payment features."""
from dataclasses import dataclass, field


@dataclass
class Session:
    history: list = field(default_factory=list)   # chat messages sent to the model, without the system prompt
    products: dict = field(default_factory=dict)  # every product returned by a search in this session, by ID
    budget_cents: int | None = None               # budget of the latest request; None means no limit


sessions: dict[str, Session] = {}


def get_session(user_id: str) -> Session:
    return sessions.setdefault(user_id, Session())
