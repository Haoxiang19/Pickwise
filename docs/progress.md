# Progress

Read this first in a new session. Updated before every commit.

## Done
- Repo setup: MIT license, .gitignore, requirements.txt.
- M1: model interface layer (`app/llm.py`, `app/money.py`).

## In progress
- M1: mock catalog and Channel3 adapter (`app/catalog.py`), next F3/F4.

## Next
- M1: F3+F4 (multi-query search, hard filter), F5+F6 (rank, top 3), F1+F2 (agent loop, ask for budget), chat endpoint and minimal page.
- M2: F8-F14. M3: F7, F15, F16. M4: eval script. (M5 and P2 not planned for this run.)

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names.

## Questions for the owner
- (none yet)

## Dev setup
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
