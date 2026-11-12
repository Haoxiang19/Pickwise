# Pickwise

Pickwise is a shopping agent I built for the PayPal AI Hackathon 2026. You tell it what you want and how much you can spend. It suggests three products, says why it picked each one, and lists the ones it left out. You pay for the one you choose through the PayPal sandbox, and you can check the order or refund it later.

## How it works

```
user message
  -> 1. Understand (model, tool call)   budget, must-have, must-not, preferences, 3-4 search queries
                                        or one question if the budget is missing
  -> 2. Search (code)                   10 results per query, merged and de-duplicated;
                                        capped at the budget when the user gave a firm maximum,
                                        plus one uncapped search to show what was ruled out
  -> 3. Hard filter (code)              over budget / out of stock / no USD offer / must-not keyword, with reasons
  -> 4. Rank (model)                    reason first, then a JSON ranking of product IDs;
                                        candidates shuffled 3 times, rankings combined by mean rank
  -> 5. Pick top 3 (code)               at most one per search query when there are 3+ queries
  -> 6. Reply (model)
```

- The agent loop is written by hand (no agent framework): `app/agent.py`.
- All model calls go through one OpenAI-compatible client, so the provider is a config change: `app/llm.py`.
- **Sets of products** ("a tent, a sleeping bag and a lantern under $300"): each item is searched and ranked on its own, and code, not the model, picks the set with the best ranks whose total fits the budget (it tries every combination of each item's top options, at most 6 items x 6 options). If even the cheapest set is over budget, nothing is ranked and the user is told what the cheapest set costs. The user can swap items and pay for the whole set in one PayPal order, which lists each product as a line item. Set recommendation has no eval numbers: the eval covers single-product requests only.
- The ranker sees only the title, price, brand and the first 200 characters of each product's description.
- Saved preferences (for example "Prefers Sony") have a strength: 0.5 when the user states one, 0.2 when it is inferred from a purchase, +0.1 each time it is confirmed and -0.2 each time it is contradicted. At the start of a new conversation the 3 strongest go to the ranker as soft preferences, and the reason names the one it used. Users can view and delete them in "What I remember".

The approaches compared for each choice are in [docs/decisions.md](docs/decisions.md); what was actually built is in [docs/implementation.md](docs/implementation.md).

## Safety design

The model can never move money.

| Tier | Actions | Triggered by |
| --- | --- | --- |
| Read-only | search and recommend, list orders | the model |
| Proposal | prepare a cart, draft a refund, remember a preference | the model proposes; carts and refunds do nothing until the user clicks |
| Money | create PayPal order, capture, refund | HTTP endpoints, only after a user click |

- Prices are computed by the server in integer cents; the model picks products by ID only. Only products returned by a search in the current session can be ordered.
- Before a cart is priced, the product is read back from the catalog, so the amount charged is a confirmed current price rather than a stored search result. A price that moved is shown to the user; a product that sold out or disappeared cannot be ordered.
- The budget is checked in code (hard filter and cart), not by the prompt. An approximate budget ("around $70") is widened by a fixed 20% in code.
- Before capture the order is read back from PayPal: capture only if it is `APPROVED` and the amount and currency equal the confirmed order. Paid only when the capture status is `COMPLETED`.
- No double charge: buttons disable on click, local status checks (capture only from `CREATED`, refund only from a paid order and only for lines not refunded yet), a lock per order around its money steps, and deterministic `PayPal-Request-Id` values (`create-{cart}`, `capture-{order}`, `refund-{order}-{line}`).
- Product titles and descriptions are treated as untrusted data; the ranking prompt says so, and the eval injects hostile listings to test it.

## PayPal APIs used (sandbox, `https://api-m.sandbox.paypal.com`)

| Purpose | Endpoint |
| --- | --- |
| Access token | `POST /v1/oauth2/token` |
| Create order (redirect flow, `payment_source.paypal.experience_context`, one line item per product with `item_total`) | `POST /v2/checkout/orders` |
| Read the order back before capture | `GET /v2/checkout/orders/{id}` |
| Capture | `POST /v2/checkout/orders/{id}/capture` |
| Refund, one order line per call with its amount | `POST /v2/payments/captures/{capture_id}/refund` |

Product search: Channel3 (`POST https://api.trychannel3.com/v1/search`).

## Evaluation

`python -m eval.run_eval --name full` runs everything and prints the table. Details: [eval/README.md](eval/README.md).

- **Test set**: 31 requests, last changed on 2026-11-11, before the search snapshot was taken (2026-11-12): 12 clear, 6 gift or vague, 5 missing budget, 4 adversarial (3 hostile listings each: hidden instructions, fake reviews, fake "real price"), 4 cross-conversation preference tests.
- **Metrics**, all computed automatically: constraint satisfaction, grounding, over-budget count, injection resistance, preference adherence, latency and cost.

### Results

Run on 2026-11-12. Model for step 1 and ranking: DeepSeek `deepseek-flash` (thinking disabled), temperature 0.0. Catalog: Channel3, replayed from [`eval/snapshot.json`](eval/snapshot.json) (created 2026-11-12), so every version sees the same products. Versions that call the model ran 3 times (seeds 101, 202, 303) and are averaged; the others ran once.

24 of the 31 requests are ranked: the 5 missing-budget requests give no budget to rank against, and 2 gift requests (`g03`, `g04`) were skipped because step 1 asked a question instead of producing a search request.

| Version | Full top 3 | Constraints | Grounding | Over-budget | Injection resistance | Memory adherence | Sec / request | Model calls | Tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | 17 / 24 | 100% | 100% | 0 | 0% | 0% | - | 0 | 0 |
| + multi-query search | 24 / 24 | 100% | 100% | 0 | 0% | 25% | - | 0 | 0 |
| + reasoning rank | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 3.97 | 1 | 2,242 |
| + multi-shuffle (3) | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 4.60 | 3 | 6,740 |
| + budget filter | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 3.96 | 1 | 2,500 |
| + memory (preference tests only) | 4 / 4 | 100% | 100% | 0 | - | 50% | 3.82 | 1 | 2,509 |

*Baseline* is one search with the user's raw words, kept in search order; each row adds one step to the row above, except *+ budget filter* and *+ memory*, which each add one step to *+ reasoning rank*. *Full top 3* counts requests that got three recommendations. *Injection resistance* is over the 4 adversarial requests, *memory adherence* over the 4 preference requests (top pick matches the saved preference). Time, calls and tokens are per request for the ranking steps only; searches are replayed from the snapshot, so search time is not included.

What the numbers say, and what they do not:

- **Multi-query search fills the top 3.** One search with the user's raw words returned fewer than three usable products for 7 of 24 requests (none at all for 3); 3 to 4 generated queries gave three for every request.
- **Constraints, grounding and over-budget are perfect in every version** because the hard filter runs in code before any ranking. They confirm the safety design; they do not separate the versions.
- **Reasoning rank kept every hostile listing out of the top 3** in all runs. The search-order versions show 0% only because the hostile listings are placed first (worst case), not because they "chose" them.
- **Memory:** with the saved preference on, the top pick matched it in 50% of runs, against 25% without (4 requests x 3 runs: a small sample).
- **Multi-shuffle and the budget filter show no difference on these metrics**, while multi-shuffle triples model calls and tokens. None of these metrics measures how relevant the picks are, so this run cannot say whether either one improves them.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --port 8000        # open http://localhost:8000
```

With no environment variables set, everything runs in mock mode. To use real services, set these environment variables (see `.env.example`; never commit `.env`):

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | OpenAI-compatible model |
| `LLM_EXTRA_BODY` | optional JSON merged into every request, e.g. `{"thinking": {"type": "disabled"}}` |
| `CHANNEL3_API_KEY` | product search |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | PayPal sandbox REST app |
| `APP_BASE_URL` | public URL used in PayPal return and cancel URLs |

The app reads these from the environment only; export them in your shell or your host's settings.

Tests: `.venv/bin/python -m pytest`

## AI disclosure

<!-- DRAFT: please review and complete in your own words before submitting. -->

- **Claude Code** was used as a coding assistant to write the code, tests and documentation, working feature by feature under the rules in `CLAUDE.md` (plan first, tests and an implementation note for every feature, no new dependencies or scope without approval). Every design choice was compared with open-source implementations first and recorded in `docs/decisions.md`.
- **Impeccable** (a design skill for Claude Code) was used for the page design: it recorded the product context in `PRODUCT.md`, presented visual directions to choose from, ran a finish review against accessibility and the payment trust cues, and wrote `DESIGN.md` from the finished page. The look was chosen by the author over several comparison rounds. The skill itself is not included in this repository (`npx impeccable skills install`).
- **At runtime**, the agent calls an OpenAI-compatible language model (DeepSeek `deepseek-flash` in this project) for understanding the request, ranking candidates and writing replies.

## License

[MIT](LICENSE)
