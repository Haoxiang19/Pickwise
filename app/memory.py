"""Preference memory (P1): one-sentence preferences per user, each with a strength in [-1, 1].

Stored in the same SQLite file as orders. Written by the agent's remember_preference tool (F18)
and by a completed purchase; used as soft preferences by the ranker (F19); viewable and
deletable by the user (F20).
"""
import sqlite3
import time
from contextlib import closing

from app import store

NEW_STRENGTH = 0.5      # our choice; the requirements only fix the update steps
CONFIRM_STEP = 0.1      # confirmed again: +0.1 (requirements section 7)
CONTRADICT_STEP = -0.2  # contradicted: -0.2
MAX_TEXT = 200
PROFILE_SIZE = 3

SCHEMA = """CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    strength REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    updated_at REAL NOT NULL
)"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def list_preferences(user_id: str) -> list[dict]:
    """All preferences of one user, strongest first."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM preferences WHERE user_id = ? ORDER BY strength DESC, id", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def _get(user_id: str, pref_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM preferences WHERE id = ? AND user_id = ?", (pref_id, user_id)).fetchone()
    return dict(row) if row else None


def _adjust(pref: dict, step: float) -> dict:
    # Rounded so repeated +0.1 steps do not drift (0.6000000000000001), and clamped to [-1, 1].
    strength = round(min(1.0, max(-1.0, pref["strength"] + step)), 2)
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE preferences SET strength = ?, evidence_count = evidence_count + 1, updated_at = ? WHERE id = ?",
                     (strength, time.time(), pref["id"]))
    return _get(pref["user_id"], pref["id"])


def remember(user_id: str, text: str, about_id: int | None = None, stance: str = "supports") -> dict:
    """F18: add a preference, or confirm / contradict an existing one. Returns the stored row.

    With `about_id`, that preference of this user is updated. Without it, a preference with the
    same text (ignoring case) is confirmed; otherwise a new one is added.
    """
    if stance not in ("supports", "contradicts"):
        raise ValueError("stance must be 'supports' or 'contradicts'")
    step = CONFIRM_STEP if stance == "supports" else CONTRADICT_STEP
    if about_id is not None:
        pref = _get(user_id, int(about_id))
        if pref is None:
            raise ValueError(f"no saved preference with id {about_id}")
        return _adjust(pref, step)
    text = " ".join(str(text or "").split())[:MAX_TEXT]
    if not text:
        raise ValueError("text is required")
    same = next((p for p in list_preferences(user_id) if p["text"].lower() == text.lower()), None)
    if same:
        return _adjust(same, step)
    strength = NEW_STRENGTH if stance == "supports" else -NEW_STRENGTH
    with closing(_connect()) as conn, conn:
        cur = conn.execute("INSERT INTO preferences (user_id, text, strength, evidence_count, updated_at) VALUES (?, ?, ?, 1, ?)",
                           (user_id, text, strength, time.time()))
    return _get(user_id, cur.lastrowid)


def record_purchase(user_id: str, items: list[dict]) -> None:
    """F18: a completed purchase supports a brand preference (exact text, so repeats are confirmations)."""
    for brand in dict.fromkeys(i.get("brand") for i in items if i.get("brand")):
        remember(user_id, f"Likes the brand {brand}")


def prompt_block(user_id: str) -> str:
    """The saved preferences as shown to the agent model, with IDs so it can confirm or contradict them."""
    prefs = list_preferences(user_id)
    if not prefs:
        return "Saved preferences of this user: none."
    lines = [f"- [{p['id']}] {p['strength']:+.2f} {p['text']}" for p in prefs]
    return "Saved preferences of this user ([id] strength text):\n" + "\n".join(lines)
