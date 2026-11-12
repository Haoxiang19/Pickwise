# PayPal Shopping Agent

A conversational shopping agent built for the PayPal AI Hackathon 2026. You describe a need in one sentence, the agent recommends 3 products with a reason each (and shows what it ruled out and why), you confirm, and you pay through the PayPal sandbox. Later you can ask for the order status or a refund.

> **Concierge-style simulation.** Products come from outside retailers (via the Channel3 search API), but the payment goes to this project's own PayPal **sandbox** merchant account. No real money moves and nothing ships. The PayPal base URL is fixed to the sandbox in code.

The focus of the project is **evaluation**: an ablation that measures what each step of the recommendation pipeline adds (see [Evaluation](#evaluation)).

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
- Saved preferences (for example "Prefers Sony") are shown only to the ranker, as soft preferences, at the start of a new conversation; the reason names the memory it used. Users can view and delete them in "What I remember".
- Without any keys, the model, the catalog and PayPal each fall back to a clearly labelled mock, so the whole flow can be clicked through.

## Safety design

The model can never move money.

| Tier | Actions | Triggered by |
| --- | --- | --- |
| Read-only | search and recommend, list orders | the model |
| Proposal | prepare a cart, draft a refund, remember a preference | the model proposes; carts and refunds do nothing until the user clicks |
| Money | create PayPal order, capture, refund | HTTP endpoints, only after a user click |

- Prices are computed by the server in integer cents; the model picks products by ID only. Only products returned by a search in the current session can be ordered.
- Before a cart is priced, the product is read back from the catalog, so the amount charged is a confirmed current price rather than a stored search result. A price that moved is shown to the user; a product that sold out or disappeared cannot be ordered.
- The budget is checked in code (hard filter and cart), not by the prompt. The model's only say is whether the budget was phrased as a firm maximum ("under $70") or an approximate one ("around $70"); the margin that follows, 20%, is a constant in the code, and the resulting limit is the single figure used for retrieval, filtering and the cart.
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

Other services: Channel3 product search (`POST https://api.trychannel3.com/v1/search`) and any OpenAI-compatible chat completions API with function calling.

## Evaluation

`python -m eval.run_eval --name full` runs everything and prints the table. Details: [eval/README.md](eval/README.md).

- **Test set**: 31 requests, written before looking at search results: 12 clear, 6 gift or vague, 5 missing budget, 4 adversarial (3 hostile listings each: hidden instructions, fake reviews, fake "real price"), 4 cross-conversation preference tests.
- **Fixed inputs**: every version replays the same saved search snapshot and the same step-1 output.
- **Metrics**: constraint satisfaction, grounding, over-budget count, ask accuracy, injection resistance, NDCG@3 (human labels 0/1/2, unlabeled products reported, never counted as 0), preference adherence, latency and cost.
- **Ablation**: baseline (one search with the raw words, search order) -> + multi-query search -> + reasoning rank -> + multi-shuffle (3 shuffles); plus budget-filtered retrieval on/off, and memory off/on for preference tests. Versions that call a model are run 3 times and averaged.

### Results

Run on 2026-11-12. Model for step 1 and ranking: DeepSeek `deepseek-flash` (thinking disabled), temperature 0.0. Catalog: Channel3, replayed from [`eval/snapshot.json`](eval/snapshot.json) (created 2026-11-12), so every version sees the same products. Versions that call the model ran 3 times (seeds 101, 202, 303) and are averaged; the others ran once. **No hand labels yet, so NDCG@3 is not reported.**

24 of the 31 requests are ranked: the 5 missing-budget requests only test the budget question, and 2 gift requests (`g03`, `g04`) were skipped because step 1 did not turn them into a search request.

| Version | Full top 3 | Constraints | Grounding | Over-budget | Injection resistance | Memory adherence | Sec / request | Model calls | Tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | 17 / 24 | 100% | 100% | 0 | 0% | 0% | - | 0 | 0 |
| + multi-query search | 24 / 24 | 100% | 100% | 0 | 0% | 25% | - | 0 | 0 |
| + reasoning rank | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 3.97 | 1 | 2,242 |
| + multi-shuffle (3) | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 4.60 | 3 | 6,740 |
| + budget filter | 24 / 24 | 100% | 100% | 0 | 100% | 25% | 3.96 | 1 | 2,500 |
| + memory (preference tests only) | 4 / 4 | 100% | 100% | 0 | - | 50% | 3.82 | 1 | 2,509 |

Columns: *Full top 3* counts requests that got three recommendations. *Injection resistance* is over the 4 adversarial requests, *memory adherence* over the 4 preference requests (top pick matches the saved preference). Time, calls and tokens are per request for the ranking steps only; searches are replayed from the snapshot, so search time is not included.

Ask accuracy (step 1 live on all 31 requests): **94%** (31 model calls, about 76k input and 3.7k output tokens).

What the numbers say, and what they do not:

- **Multi-query search fills the top 3.** One search with the user's raw words returned fewer than three usable products for 7 of 24 requests (none at all for 3); 3 to 4 generated queries gave three for every request.
- **Constraints, grounding and over-budget are perfect in every version** because the hard filter runs in code before any ranking. They confirm the safety design; they do not separate the versions.
- **Reasoning rank kept every hostile listing out of the top 3** in all runs. The search-order versions show 0% only because the hostile listings are placed first (worst case), not because they "chose" them.
- **Memory:** with the saved preference on, the top pick matched it in 50% of runs, against 25% without (4 requests x 3 runs: a small sample).
- **Multi-shuffle and the budget filter show no difference on these automatic metrics**, while multi-shuffle triples model calls and tokens. Whether either improves relevance needs the hand labels (NDCG@3), which are not done.

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

### Deploy on Render

The repository has a Render Blueprint, [`render.yaml`](render.yaml): a free Python web service, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT` with one worker (sessions and carts are in memory).

1. On Render: New > Blueprint, and pick this repository.
2. Enter the values Render asks for: `LLM_API_KEY`, `CHANNEL3_API_KEY`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `APP_BASE_URL`. The model URL and name are set in `render.yaml`; change them there to use another provider.
3. After the first deploy, set `APP_BASE_URL` to the service URL (for example `https://pickwise.onrender.com`) and deploy again. PayPal sends the buyer back to this URL.

Any variable left empty makes that service run as a labelled mock.

## Known limitations

- Orders are a sandbox simulation; products are not really bought from the retailers.
- Render's free instance has no persistent disk, sleeps after 15 minutes and can restart at any time. A restart loses sessions, carts, the SQLite orders and saved preferences, so an order paid before a restart can no longer be looked up or refunded in the app. The first request after a sleep is slow.
- Up to 6 different products per order; a refund covers whole lines (one product with all its units), not single units; no shipping or tax.
- A set's first search knows only the total budget, so a search that returns only expensive products for one item can make a set impossible; the set treats every item as equally important.
- No login: a random ID in an HttpOnly cookie identifies the user.
- Product variants (size, colour) are ignored: the agent orders a product, not a specific variant.
- The price is confirmed when the product is chosen, then held for the 15-minute quote; it is not checked again at the moment of payment.
- Merchant buy links are not shown, so no affiliate commission is earned.
- The keyless mock agent understands only simple phrasings; it exists so the flow can be demonstrated without keys.
- The double-charge lock assumes a single worker process.
- Checked against the real services on 2026-11-12 (Channel3 search, DeepSeek `deepseek-flash` function calling, and a PayPal sandbox payment from a local run); the deployed instance is checked separately after each deploy.
- The chat page keeps the current conversation in the browser's local storage, so it survives the PayPal round trip and a reload, but not a change of browser.

## Design basis

The pipeline is *informed by* these papers; it does not implement any of them in full.

- Reason first, then rank: [BracketRank](https://arxiv.org/pdf/2604.08834)
- Listwise ranking: [How Good are LLM-based Rerankers?](https://aclanthology.org/2025.findings-emnlp.305.pdf)
- Shuffle several times and aggregate: [Permutation Self-Consistency](https://aclanthology.org/2024.naacl-long.129.pdf) (we use 3 shuffles and mean rank instead of 20 shuffles and Kemeny aggregation)
- Rankings change with input order: [Position Bias Undermines Preference Consistency](https://arxiv.org/pdf/2608.03091)
- Multi-query search must be measured: [A Reproducibility Study of LLM-Based Query Reformulation](https://arxiv.org/html/2604.27421v1); [LLM-based Query Expansion Under Control](https://cs.uwaterloo.ca/~jimmylin/publications/Sadeghi_Lin_SIGIR-AP2026b.pdf)
- Less but more precise information for the ranker: [CAIRO](https://arxiv.org/pdf/2608.20801)
- Preference strength update rule: [MARS](https://arxiv.org/abs/2605.14401)

Design decisions, with the open-source implementations compared, are in [docs/decisions.md](docs/decisions.md); what was actually built is in [docs/implementation.md](docs/implementation.md).

## AI tools used

<!-- DRAFT: please review and complete in your own words before submitting. -->

- **Claude Code** was used as a coding assistant to write the code, tests and documentation, working feature by feature under the rules in `CLAUDE.md` (plan first, tests and an implementation note for every feature, no new dependencies or scope without approval). Every design choice was compared with open-source implementations first and recorded in `docs/decisions.md`.
- **Impeccable** (a design skill for Claude Code) was used for the page design: it recorded the product context in `PRODUCT.md`, presented visual directions to choose from, ran a finish review against accessibility and the payment trust cues, and wrote `DESIGN.md` from the finished page. The look was chosen by the author over several comparison rounds. The skill itself is not included in this repository (`npx impeccable skills install`).
- **At runtime**, the agent calls an OpenAI-compatible language model (planned: DeepSeek) for understanding the request, ranking candidates and writing replies.
- Relevance labels for the evaluation are assigned by hand, not by a model.

## License

[MIT](LICENSE)
