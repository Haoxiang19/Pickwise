# Progress

Read this first in a new session. Updated before every commit. Last update: 2026-11-11.

## Done
- Repo setup: MIT license, .gitignore, requirements.txt, `.env.example`.
- M1: model interface layer (`app/llm.py`, `app/money.py`).
- M1: product search and mock catalog (`app/catalog.py`, `app/mock_catalog.json`).
- F3 multi-query search, F4 hard filter (`app/recommend.py`).
- F5 reasoning rank, F6 top-3 pick and result shape (`app/recommend.py`).
- F1 parse request, F2 ask for budget: agent loop, keyless mock agent, /api/chat, minimal page. **M1 done** (in mock mode a request gives 3 recommendations; tests pass).
- F8 order summary: server-priced cart, 15-minute quote, prepare_cart tool, Choose button.
- F9 confirm, F10 create PayPal order and redirect (`app/checkout.py`, `app/paypal.py`, `app/paypal_mock.py`, SQLite orders in `app/store.py`).
- F11 verify then capture, F13 cancel/failure messages, F14 result page.
- F12 no double charge (lock + local status + request IDs + disabled button). **M2 done in mock mode**; its real done-criterion (one real sandbox payment) needs PayPal sandbox credentials.
- F7 refine from feedback (prompt rule; keyless mock handles cheaper / different brand / follow-up exclusions).
- F15 order status (`get_orders` read-only tool, filtered by the cookie user).
- F16 refund (`draft_refund` proposal tool + Confirm refund endpoint). **M3 features done**; page design (Impeccable) and Render deploy not done (need the owner).
- M4 eval script: `eval/run_eval.py`, `eval/metrics.py`, 27 test requests, 12 hostile listings, empty `labels.json`. Ran in keyless mode only (mock numbers, not results).
- State: 111 tests pass (`pytest`). Whole flow clicked through in the browser in keyless mode: ask budget, recommend, ruled-out list, refine, choose, Confirm, mock PayPal approve and cancel, success page, order status, refund.

## In progress
- Nothing. This run stopped at the end of M4 as instructed (no M5, no P2).

## Next steps for the owner (in order)
1. Put keys in `.env` (copy `.env.example`; never commit it): `LLM_*`, `CHANNEL3_API_KEY`, `PAYPAL_CLIENT_ID/SECRET`. For DeepSeek set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`. Note: the app reads environment variables only; it does not load `.env` by itself (no extra dependency). Export them in the shell, or use `uvicorn --env-file .env` (needs the `python-dotenv` package, not installed).
2. Check Channel3 with one real search: field names and that `offers[].price.price` is in dollars (a cents value would be a 100x error). Fix `catalog.normalize` if not.
3. Check DeepSeek function calling with the app: does it ask for the budget, call `recommend` with good queries, keep earlier conditions on refine.
4. One real sandbox payment with a sandbox personal account (M2 done-criterion). Check: `payer-action` link, read-back status `APPROVED`, capture status, refund status.
5. Impeccable design (`/impeccable init`, `craft`, `audit`), then deploy to Render with `APP_BASE_URL` set to the public URL.
6. Real eval: `python -m eval.run_eval --name full` (with both model and Channel3 keys it creates `eval/snapshot.json` once), label `runs/full/to_label.json` into `eval/labels.json`, run again for NDCG@3.

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names, ranking JSON quality.
- No real Channel3 call: field names and the dollar unit of `offers[].price.price`.
- No real PayPal sandbox call: token, create (`payer-action` link), get, capture, refund are tested only against fakes and the mock. PayPal's real error body shape and the query parameters it appends to return/cancel URLs are not observed.
- Render deploy, phone-width layout, `secure` cookie behind Render's proxy.

## Questions for the owner
- **Capture with no answer from PayPal** (network error or HTTP 5xx): requirements say "anything else -> CAPTURE_FAILED". I kept the order `CREATED` with a note and a "Check again" link instead, because the capture may have succeeded at PayPal and "Nothing was charged" could be false. A retry uses the same `capture-{id}` request ID. Please confirm or tell me to switch to `CAPTURE_FAILED`.
- **Capture status `PENDING`**: per requirements it becomes `CAPTURE_FAILED` with the message "Payment failed. Nothing was charged." For a real pending capture the money may still move. Kept as specified; the note shows the status. OK?
- **Refund status other than `COMPLETED`** (e.g. `PENDING`): order stays `COMPLETED` with a note; a retry uses the same request ID. OK?
- **Hostile listing position in the eval**: injected in front of the search results (worst case). For versions without reasoning rank, injection resistance then only reflects that placement. Keep, or append at the end / random position?
- **`SNAPSHOT_MODE`** (listed in requirements section 10) is not used: the eval decides by itself (load `snapshot.json` if present, otherwise build it once), and the app always searches live. What should it control?
- **Eval run logs** (`eval/runs/`) are git-ignored. Commit the real run's logs as evidence for the README numbers?
- **Order table extras**: added `approval_url` (so a second Confirm returns the same link without calling PayPal) and `note` (the reason shown for a failure). Not in the data section of requirements.
- **New modules not in the suggested layout**: `app/checkout.py` (money flow: confirm, return, cancel, refund, so `main.py` stays thin and the flow is unit-testable), `app/money.py` (cents helpers), `app/paypal_mock.py` and `app/mock_agent.py` (keyless stand-ins kept out of the real code paths).
- **Budget question is a prompt rule only** (F2). Code does not stop the model from searching without a budget; ask accuracy in the eval measures it. Add a code guard?

## Dev setup
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
- Run: `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` (`.claude/launch.json` has the same).
- Tests: `.venv/Scripts/python -m pytest` (temp files go to `.pytest_tmp/`, set in pytest.ini because the system temp dir was not writable here).
- `uvicorn --reload` did not always pick up changes on this Windows machine; restart the server after edits.
- Python's default file encoding here is GBK: pass `encoding="utf-8"` in any script that edits files.
- Local `orders.db` is git-ignored; delete it to start with no orders.
