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
- Retrieval asks the catalog for affordable products (`filters.price.max_price`), plus one extra unfiltered search so the ruled-out list still works. An approximate budget ("around $70") is widened by 20% in code and that one figure is used everywhere. New eval row "+ budget filter"; the snapshot captures the capped results in the same pass.
- F20 'What I remember' panel: list and delete own entries (`GET/DELETE /api/memory`). **M5 done in keyless mode.**
- F21 multi-item cart (commit 1 of the multi-item work order): up to 6 products per cart, server total, budget on the total, `prepare_cart` and `/api/cart` accept `items`, one summary row per item. Research for F21-F23 recorded in `docs/decisions.md`.
- F21 PayPal line items (commit 2): every create request, single-item orders included, now carries `purchase_units[0].items` and `amount.breakdown.item_total`; the code refuses to send if the items do not add up to the amount, and the mock checks the same sums.
- F22 core (commit 3): `parse_bundle`, `best_combo`, `recommend_bundle` in `app/recommend.py`, tested with a fake catalog. Owner's choice: a product found for several items belongs to the first item.
- F22 in the app (commit 4): `recommend_bundle` agent tool, keyless mock reads "a tent, a sleeping bag and a lantern under $500" as a set and "buy the set" as a cart, 5 products added to the mock catalog for the demo, page shows one group per item with radio buttons and a "Review this set" button. Clicked through in the browser in keyless mode: $500 / $180 / $100 sets, swap and review, Confirm, mock approve, status, full refund; single-product purchase still works.
- F23 refund by line (commit 5): `draft_refund` / the refund endpoint take line numbers; one PayPal refund per line with its amount and request ID `refund-{order}-{line}`; `PARTIALLY_REFUNDED` until every line is refunded. A failed line now returns the order with a note (HTTP 200) instead of HTTP 400. Clicked through in keyless mode: set bought, line 2 refunded, then the rest; single-product refund still works.
- Architecture review (2026-11-11): money steps now take one lock per order instead of one global lock, so a slow PayPal call no longer blocks other users. A PayPal 4xx whose body is not JSON is now reported as `HTTP_4xx` (a refusal) instead of `NETWORK_ERROR` (unknown outcome).
- Purchase-written brand preferences start at 0.2 (stated ones at 0.5) and name the category ("Likes the brand Coleman for tents"), so a set purchase no longer fills the memory profile. The agent prompt now tells the model to keep the scope the user gave when it writes a preference (prompt rule only, not checked on a real model).
- State: 224 tests pass (`pytest`). Whole flow clicked through in the browser in keyless mode: ask budget, recommend, ruled-out list, refine, choose, Confirm, mock PayPal approve and cancel, success page, order status, refund, save a preference, new conversation using it, view and delete it.

## In progress
- M5 (F17-F20) was approved by the owner on 2026-11-11 and is done in keyless mode.
- P2 "multiple items per order" is done in keyless mode as F21 (multi-item cart, PayPal line items), F22 (set recommendation) and F23 (refund by line), in 5 commits. The work order `docs/multi-item-plan.md` was deleted on 2026-11-11 after completion, as it asked; what was built is in `docs/implementation.md`, the research in `docs/decisions.md`, and the file remains in git history.

## To do: make every feature visible on the page (owner approved the list, 2026-11-11; not started)
Found in the real run: a recommendation takes about 20 seconds with no feedback, and order status, refunds, sets
and preferences can only be reached by typing the right sentence. Only `static/index.html` changes; no new
endpoint, and payment and refund safety is untouched.
1. **Waiting message**: right after a message is sent, show "Searching and ranking products... (about 20 seconds)"
   and replace it with the reply.
2. **Entry points**:
   - example buttons under the input that send `a tent, a sleeping bag and a lantern under $300`,
     `I always buy Sony` and `my orders`;
   - on an order card, "Refund this item" per line and "Refund the rest", which send
     `refund item N of order X` / `refund order X` to the chat, so the agent still drafts every refund (F16, F23)
     and money moves only on Confirm refund.
3. **Success page note**: say this is a sandbox simulation and nothing ships, and that the order can be checked or
   refunded from the chat or the buttons.

## Next steps for the owner (in order)
1. Put keys in `.env` (copy `.env.example`; never commit it): `LLM_*`, `CHANNEL3_API_KEY`, `PAYPAL_CLIENT_ID/SECRET`. For DeepSeek set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`. Note: the app reads environment variables only; it does not load `.env` by itself (no extra dependency). Export them in the shell, or use `uvicorn --env-file .env` (needs the `python-dotenv` package, not installed).
2. Check Channel3 with one real search, **before building the eval snapshot** (the snapshot stores normalized products, so a mapping bug would be baked into it). Print one raw response and confirm:
   - the price is in dollars, and whether the field is `price.price` or `price.amount` (the code accepts both, but only one should be in use);
   - which `availability` values actually occur (the code treats anything outside `OutOfStock`/`SoldOut`/`PreOrder`/`BackOrder` as buyable and logs unknown values once);
   - that `brands[0].name`, `images[].is_main_image` and `category.title` are populated;
   - what `GET /v1/products/{id}` returns (the product at the top level, or wrapped in `"product"`); the code accepts both;
   - whether `offers[].url` and `max_commission_rate` are populated, and how many results carry a `variants` object with a `selected` entry. Both feed the deferred decisions below.
   Budget: one eval snapshot costs roughly 230 search credits. The hackathon promo code `PAYPAL-HACKATHON-2026` gives a key 20,000 free credits, and Channel3 tops it up on request in the #channel3 channel of the PayPal Discord (sponsor page https://paypalaihackathon.devpost.com/details/channel3, read 2026-11-11); without the code the plan is 1,000 per month (each request is searched once per query, once on the raw text, and once per query capped at its budget), so do not rebuild it casually. There is no test key; every call is billed.
3. Check DeepSeek function calling with the app: does it ask for the budget, call `recommend` with good queries, keep earlier conditions on refine.
4. One real sandbox payment with a sandbox personal account (M2 done-criterion). Check: `payer-action` link, read-back status `APPROVED`, capture status, refund status. Make it a **two-item** order and refund **one line first, then the other**: that single run checks the line items in the create body (F21) and two refunds with an amount on one capture (F23).
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

## Deferred: a usage cap for a public deploy (owner, 2026-11-11: not now)

`/api/chat` needs no login, so a public Render URL with real keys lets anyone spend Channel3 credits
(20,000 with the hackathon code, topped up on request, so the real exposure is the model bill)
and model calls (one set request: up to 12 searches and 18 ranking calls). Not added for now.
What the official rules (https://paypalaihackathon.devpost.com/rules) say, checked 2026-11-11:
- Nothing about API usage, rate limits or costs.
- Deploying is optional: setup instructions in the repo OR a hosted demo URL; judges must be able to
  run or use a working build. Judges may also judge from the description and video alone.
- A provided demo must stay available "free of charge and without any restriction" until the judging
  period ends: **Dec 15, 2026, 8:00 am PT**. Judging runs Dec 1-15.
- Testing instructions should include any credentials or API keys needed; ours stay in Render's
  environment variables, never in the repo.
If a cap is added before deploying: degrade to the labelled mock when a daily total is reached, never
refuse the request, so a judge can always finish the flow (refusing would break "without any restriction").

## Verified against real services (2026-11-11, from the dev machine)
- **Channel3**: search and `GET /v1/products/{id}` work. The price is `offers[].price.price` as a dollar number (34.99 -> 3499 cents); currency `USD`; `availability` seen only as `InStock`; `brands[0].name`, `images[].is_main_image` and `category.title` are filled; the product lookup returns the product at the top level (no `product` wrapper); `filters.price.max_price` held ($100 cap, 10 of 10 results under it). 5 of 10 tent results carry a `variants` object; offers carry `max_commission_rate` (e.g. 0.014). Hackathon credits apply (see Deferred).
- **DeepSeek** (`deepseek-flash`, thinking disabled through `LLM_EXTRA_BODY`): the model ID is accepted, replies carry no `reasoning_content`, and `usage.prompt_tokens` / `usage.completion_tokens` exist. In a 6-turn agent run it asked for the budget and did not search; called `recommend` with 4 queries at $120; on "cheaper" kept the $120 budget but searched cheaper queries (results $35-$60); on "I always buy Nike" saved a preference and searched Nike; split "a tent, a sleeping bag and a lantern under $300" into 3 items with 2 queries each (set $164.93); on "buy the set" called `prepare_cart` with the 3 chosen IDs. 29 model calls, about 69k input and 10k output tokens for the 6 turns.
- **PayPal sandbox**: token works; create with line items and `breakdown.item_total` accepted (F21), items read back as sent with a 127-character name cut; the same `PayPal-Request-Id` returned the same order; read-back status `PAYER_ACTION_REQUIRED`; the `payer-action` link is on `www.sandbox.paypal.com`.

## Found in the real run (not fixed)
- **Latency**: a recommendation turn took 18-25 seconds. Measured on one request (2026-11-11): the 4 capped Channel3 searches run one after another and took 12.0 s, the extra uncapped search 2.9 s, ranking 4.0-4.4 s with 1 shuffle and 4.3-4.8 s with 3 (the shuffles run in parallel), the agent's first call 2.2 s. So searching, not ranking, is the bottleneck: `rank_shuffles` 1 saves two thirds of the ranking cost but almost no time. Running the searches in parallel would remove most of the wait (not done; needs the owner's OK).
- **Preference scope**: "I always buy Nike" was saved as "Always buys Nike shoes." during a running-shoe conversation, although the prompt says to keep the user's scope.

## Not verified (needs real services)
- Capture after a real buyer approval, the read-back `APPROVED` status, and refunds with an amount on a real capture (F23), including two partial refunds on one capture. Needs a buyer login in the sandbox.
- Ranking JSON quality over many requests, and the eval on real data.
- PayPal's real error body shape and the query parameters it appends to the return/cancel URLs.
- Render deploy, phone-width layout on a real phone, `secure` cookie behind Render's proxy.

## Questions for the owner
- **The margin for an approximate budget is 20%** (`recommend.APPROXIMATE_MARGIN`), so "around $70" allows up to $84, rounded up to a whole dollar. Chosen by the owner on 2026-11-11; change the constant to adjust.
- **The price cap is on by default in the app** (`DEFAULT_FLAGS["budget_filter"]`), which costs one extra search per request with a budget. Turn it off if credits get tight; the eval measures whether it is worth it.
- **Capture with no answer from PayPal** (network error or HTTP 5xx): requirements say "anything else -> CAPTURE_FAILED". I kept the order `CREATED` with a note and a "Check again" link instead, because the capture may have succeeded at PayPal and "Nothing was charged" could be false. A retry uses the same `capture-{id}` request ID. Please confirm or tell me to switch to `CAPTURE_FAILED`.
- **Capture status `PENDING`**: per requirements it becomes `CAPTURE_FAILED` with the message "Payment failed. Nothing was charged." For a real pending capture the money may still move. Kept as specified; the note shows the status. OK?
- **Refund status other than `COMPLETED`** (e.g. `PENDING`): that line is not marked refunded, the order keeps its status with a note naming the line; a retry uses the same request ID. OK?
- **Hostile listing position in the eval**: injected in front of the search results (worst case). For versions without reasoning rank, injection resistance then only reflects that placement. Keep, or append at the end / random position?
- **`SNAPSHOT_MODE`** (listed in requirements section 10) is not used: the eval decides by itself (load `snapshot.json` if present, otherwise build it once), and the app always searches live. What should it control?
- **Eval run logs** (`eval/runs/`) are git-ignored. Commit the real run's logs as evidence for the README numbers?
- **Order table extras**: added `approval_url` (so a second Confirm returns the same link without calling PayPal) and `note` (the reason shown for a failure). Not in the data section of requirements.
- **New modules not in the suggested layout**: `app/checkout.py` (money flow: confirm, return, cancel, refund, so `main.py` stays thin and the flow is unit-testable), `app/money.py` (cents helpers), `app/paypal_mock.py` and `app/mock_agent.py` (keyless stand-ins kept out of the real code paths).
- **Preference strengths: decided** (owner, 2026-11-11). Set in code, not by the model: a stated preference starts at 0.5 (-0.5 for a new 'contradicts' without an ID), one inferred from a purchase at 0.2 and scoped to its category; +0.1 / -0.2 per confirmation / contradiction. The model only decides whether to save, the sentence, and supports vs contradicts.
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
