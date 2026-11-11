# Progress

Read this first in a new session. Updated before every commit.

## Done
- Repo setup: MIT license, .gitignore, requirements.txt.
- M1: model interface layer (`app/llm.py`, `app/money.py`).
- M1: product search and mock catalog (`app/catalog.py`, `app/mock_catalog.json`).
- F3 multi-query search, F4 hard filter (`app/recommend.py`).
- F5 reasoning rank, F6 top-3 pick and result shape (`app/recommend.py`).

## In progress
- F1+F2: agent loop with tools, keyless rule-based agent, /api/chat and minimal page (`app/agent.py`, `app/mock_agent.py`, `app/store.py`, `app/main.py`, `static/index.html`).

## Next
- After F1+F2: M1 is done; start M2 (F8-F14).
- M2: F8-F14. M3: F7, F15, F16. M4: eval script. (M5 and P2 not planned for this run.)

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names.
- No real Channel3 call: field names and the dollar unit of `offers[].price.price`.

## Questions for the owner
- (none yet)

## Dev setup
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
