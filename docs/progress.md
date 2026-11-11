# Progress

Read this first in a new session. Updated before every commit.

## Done
- Repo setup: MIT license, .gitignore, requirements.txt.
- M1: model interface layer (`app/llm.py`, `app/money.py`).
- M1: product search and mock catalog (`app/catalog.py`, `app/mock_catalog.json`).
- F3 multi-query search, F4 hard filter (`app/recommend.py`).
- F5 reasoning rank, F6 top-3 pick and result shape (`app/recommend.py`).
- F1 parse request, F2 ask for budget: agent loop, keyless mock agent, /api/chat, minimal page. **M1 done** (in mock mode a request gives 3 recommendations; tests pass).
- F8 order summary: server-priced cart, 15-minute quote, prepare_cart tool, Choose button.

## In progress
- M2: F9+F10 Confirm creates the order row and the PayPal order (`app/paypal.py` with mock), redirect to approval.

## Next
- M2: F8-F14. M3: F7, F15, F16. M4: eval script. (M5 and P2 not planned for this run.)

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names.
- No real Channel3 call: field names and the dollar unit of `offers[].price.price`.

## Questions for the owner
- (none yet)

## Dev setup
- Run: `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` (`.claude/launch.json` has the same).
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
