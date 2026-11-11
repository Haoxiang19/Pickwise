# Progress

Read this first in a new session. Updated before every commit.

## Done
- Repo setup: MIT license, .gitignore, requirements.txt.
- M1: model interface layer (`app/llm.py`, `app/money.py`).
- M1: product search and mock catalog (`app/catalog.py`, `app/mock_catalog.json`).
- F3 multi-query search, F4 hard filter (`app/recommend.py`).

## In progress
- F5 reasoning rank + F6 top-3 pick (`app/recommend.py`): writing code and decisions.md entry.

## Next
- M1: F1+F2 (agent loop, ask for budget), chat endpoint and minimal page.
- M2: F8-F14. M3: F7, F15, F16. M4: eval script. (M5 and P2 not planned for this run.)

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names.
- No real Channel3 call: field names and the dollar unit of `offers[].price.price`.

## Questions for the owner
- (none yet)

## Dev setup
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
