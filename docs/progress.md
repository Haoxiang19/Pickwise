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
- F17 multi-shuffle ranking (3 shuffles in parallel, mean rank, unlisted = 7); eval row "+ multi-shuffle".
- F18 preference memory write (`app/memory.py`, `remember_preference` tool, purchase writes "Likes the brand X").
- F19 memory use: profile (top 3 positive) fixed per conversation, ranker-only soft preference, reason names the memory; New conversation button; eval adds 4 preference requests and the "+ memory" version.
- Page states the concierge-style simulation (requirements section 1); README drafted with an empty results table.
- Channel3 compatibility pass against the docs: price field fallback, availability semantics, one retry on 429/5xx, `country` in the request.
- Prices are refreshed from the catalog before a cart is priced (free `GET /v1/products/{id}`); a changed price is shown to the user, a vanished or sold-out product refuses the cart.
- Retrieval asks the catalog for affordable products (`filters.price.max_price`) when the model marks the budget as firm, plus one extra unfiltered search so the ruled-out list still works. New eval row "+ budget filter"; the snapshot captures the capped results in the same pass.
- F20 'What I remember' panel: list and delete own entries (`GET/DELETE /api/memory`). **M5 done in keyless mode.**
- State: 167 tests pass (`pytest`). Whole flow clicked through in the browser in keyless mode: ask budget, recommend, ruled-out list, refine, choose, Confirm, mock PayPal approve and cancel, success page, order status, refund, save a preference, new conversation using it, view and delete it.

## In progress
- Nothing. M5 (F17-F20) was approved by the owner on 2026-11-11 and is done in keyless mode. P2 not started.

## Next steps for the owner (in order)
1. Put keys in `.env` (copy `.env.example`; never commit it): `LLM_*`, `CHANNEL3_API_KEY`, `PAYPAL_CLIENT_ID/SECRET`. For DeepSeek set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`. Note: the app reads environment variables only; it does not load `.env` by itself (no extra dependency). Export them in the shell, or use `uvicorn --env-file .env` (needs the `python-dotenv` package, not installed).
2. Check Channel3 with one real search, **before building the eval snapshot** (the snapshot stores normalized products, so a mapping bug would be baked into it). Print one raw response and confirm:
   - the price is in dollars, and whether the field is `price.price` or `price.amount` (the code accepts both, but only one should be in use);
   - which `availability` values actually occur (the code treats anything outside `OutOfStock`/`SoldOut`/`PreOrder`/`BackOrder` as buyable and logs unknown values once);
   - that `brands[0].name`, `images[].is_main_image` and `category.title` are populated;
   - what `GET /v1/products/{id}` returns (the product at the top level, or wrapped in `"product"`); the code accepts both;
   - whether `offers[].url` and `max_commission_rate` are populated, and how many results carry a `variants` object with a `selected` entry. Both feed the deferred decisions below.
   Budget: one eval snapshot costs roughly 230 search credits out of 1,000 free per month (each request is searched once per query, once on the raw text, and once per query capped at its budget), so do not rebuild it casually. There is no test key; every call is billed.
3. Check DeepSeek function calling with the app: does it ask for the budget, call `recommend` with good queries, keep earlier conditions on refine.
4. One real sandbox payment with a sandbox personal account (M2 done-criterion). Check: `payer-action` link, read-back status `APPROVED`, capture status, refund status.
5. Impeccable design (`/impeccable init`, `craft`, `audit`), then deploy to Render with `APP_BASE_URL` set to the public URL.
6. Real eval: `python -m eval.run_eval --name full` (with both model and Channel3 keys it creates `eval/snapshot.json` once), label `runs/full/to_label.json` into `eval/labels.json`, run again for NDCG@3. The table now has 5 versions (incl. + multi-shuffle and + memory) and a memory-adherence column.
7. README is drafted: fill the Results table only from a real run, and rewrite the "AI tools used" draft section in your own words. Still missing for submission: the video, the public GitHub repo (nothing pushed), and the Devpost entry.

## Deferred until a real Channel3 key is connected

Both are safe to leave as they are: the current behaviour needs no extra work and breaks no rule.
Decide each one after looking at a real response (step 2 above).

**Merchant buy links and the commission disclosure.** `offers[].url` is an attributed buy link
(`buy.trychannel3.com/...`) that pays a commission, of which Channel3 keeps half. Its docs require a
disclosure near such links on every page, screen or message that shows them. The app stores the URL
but never renders it, so nothing is required today.
- Look at: whether the URLs resolve to real retailer pages, and whether `max_commission_rate` is above 0.
- If they are shown: add a "View at retailer" link to each card **and**, in the same change, the
  disclosure sentence from Channel3's commissions page near the cards. Never one without the other.
  Then say in the README that the app earns a commission, next to the concierge-simulation note.
- Against showing them: it gives the user a second way to buy that bypasses the PayPal flow the demo
  is about, and blurs the line between the real retailer and this project's sandbox merchant.
- Doing nothing keeps the README's current wording ("merchant buy links are not shown") true.

**Product variants (size, colour).** One product can cover several buyable variations. The app
ignores them, so an order says "Brooks Ghost 16" with no size. Channel3 says variant support is still
rolling out, and search results do not carry live per-variant stock.
- Look at: how many real results have a `variants` object, and whether `selected` is filled in on
  search results or only on product detail.
- If most products have no variants: leave it, and keep the README limitation as it is.
- If `selected` is filled in: show it on the card and copy it into the cart item and the order
  snapshot. Display only, no picker; small and does not touch pricing.
- A real picker (the user chooses the size) is post-hackathon: variant prices differ, so the cart,
  the order row and the PayPal amount would all have to key on the variant instead of the product,
  which is P0 payment behaviour.

## Not verified (needs real services)
- No real model call made yet: function calling on DeepSeek, model ID, `usage` field names, ranking JSON quality, whether it saves/uses preferences sensibly, cost of 3 parallel ranking calls.
- No real Channel3 call: field names and the dollar unit of `offers[].price.price`.
- No real PayPal sandbox call: token, create (`payer-action` link), get, capture, refund are tested only against fakes and the mock. PayPal's real error body shape and the query parameters it appends to return/cancel URLs are not observed.
- Render deploy, phone-width layout, `secure` cookie behind Render's proxy.

## Questions for the owner
- **The price cap is on by default in the app** (`DEFAULT_FLAGS["budget_filter"]`), which costs one extra search per request with a budget. Turn it off if credits get tight; the eval measures whether it is worth it.
- **Capture with no answer from PayPal** (network error or HTTP 5xx): requirements say "anything else -> CAPTURE_FAILED". I kept the order `CREATED` with a note and a "Check again" link instead, because the capture may have succeeded at PayPal and "Nothing was charged" could be false. A retry uses the same `capture-{id}` request ID. Please confirm or tell me to switch to `CAPTURE_FAILED`.
- **Capture status `PENDING`**: per requirements it becomes `CAPTURE_FAILED` with the message "Payment failed. Nothing was charged." For a real pending capture the money may still move. Kept as specified; the note shows the status. OK?
- **Refund status other than `COMPLETED`** (e.g. `PENDING`): order stays `COMPLETED` with a note; a retry uses the same request ID. OK?
- **Hostile listing position in the eval**: injected in front of the search results (worst case). For versions without reasoning rank, injection resistance then only reflects that placement. Keep, or append at the end / random position?
- **`SNAPSHOT_MODE`** (listed in requirements section 10) is not used: the eval decides by itself (load `snapshot.json` if present, otherwise build it once), and the app always searches live. What should it control?
- **Eval run logs** (`eval/runs/`) are git-ignored. Commit the real run's logs as evidence for the README numbers?
- **Order table extras**: added `approval_url` (so a second Confirm returns the same link without calling PayPal) and `note` (the reason shown for a failure). Not in the data section of requirements.
- **New modules not in the suggested layout**: `app/checkout.py` (money flow: confirm, return, cancel, refund, so `main.py` stays thin and the flow is unit-testable), `app/money.py` (cents helpers), `app/paypal_mock.py` and `app/mock_agent.py` (keyless stand-ins kept out of the real code paths).
- **New preference starting strength is 0.5** (requirements fix only +0.1 / -0.2). A new 'contradicts' without an ID starts at -0.5. OK?
- **Preference adherence = top recommendation contains the keyword** (title or brand). Requirements do not define 'respects'; top-1 is the strict choice. OK?
- **App default for `rank_shuffles` is 3** (so the app uses F17 by default, 3x ranking cost). Set to 1 for cheaper demos?
- **Budget question is a prompt rule only** (F2). Code does not stop the model from searching without a budget; ask accuracy in the eval measures it. Add a code guard?

## Dev setup
- `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt` (Windows path; use `.venv/bin/` elsewhere).
- Run: `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` (`.claude/launch.json` has the same).
- Tests: `.venv/Scripts/python -m pytest` (temp files go to `.pytest_tmp/`, set in pytest.ini because the system temp dir was not writable here).
- `uvicorn --reload` did not always pick up changes on this Windows machine; restart the server after edits.
- Python's default file encoding here is GBK: pass `encoding="utf-8"` in any script that edits files.
- Local `orders.db` is git-ignored; delete it to start with no orders.
