# Pickwise

Pickwise is a shopping agent I built for the PayPal AI Hackathon 2026. You tell it what you want and how much you can spend. It suggests three products, says why it picked each one, and lists the ones it left out. You pay for the one you choose through the PayPal sandbox, and you can check the order or refund it later.

## What it does

- **Three picks, each with a reason.** The model turns your request into 3 to 4 searches on Channel3. Code removes anything over budget, out of stock or matching what you said you don't want, and the model ranks the rest (three shuffled passes, averaged). Products it ruled out are listed with the reason. No budget given? It asks for one first.
- **A set under one budget.** "A smart mug, a notebook and a candle under $200": each item is searched and ranked on its own, and code picks the best combination that fits the total. You can swap any item before paying.
- **Pay only when you click.** The server prices the cart in cents. Confirm creates a PayPal order; after you approve it on PayPal, the server reads the order back, checks the amount, and only then captures.
- **Orders and refunds.** Check your orders on the Orders page or in the chat. A refund can be for one line or the whole order; the agent drafts it and nothing is sent until you click Confirm refund.
- **Remembers what you like.** Lasting preferences ("I prefer balsam and cedar scents") are saved, used as soft hints in later conversations, and named in the reason when they matter. You can see and delete them in "What I remember".
- **Works without keys.** With no API keys, the model, the catalog and PayPal each switch to a labelled mock, so the whole flow can be clicked through.

## Safety

The model can never move money. It can search, recommend, prepare a cart and draft a refund; creating a PayPal order, capturing and refunding happen only in HTTP endpoints after a user click.

- Prices and the budget are checked by the server in integer cents; the model only picks product IDs from the current search.
- Before capture, the order is read back from PayPal and captured only if it is approved and the amount matches.
- Create, capture and refund requests carry a fixed `PayPal-Request-Id`, so a repeated click or reload never charges twice.

## Built with

- **PayPal Developer Platform** (sandbox): Orders v2 to create an order with one line item per product, read it back and capture it; Payments v2 to refund one line at a time.
- **Channel3**: product search.
- **DeepSeek** (`deepseek-flash`): understands the request, ranks the products and writes the replies. Any OpenAI-compatible model works; every call goes through one client, [`app/llm.py`](app/llm.py).
- **Render**: hosting, set up in [`render.yaml`](render.yaml).
- **Python, FastAPI, SQLite**, and one static HTML page with plain JavaScript. The agent loop is written by hand in [`app/agent.py`](app/agent.py), without an agent framework.

Design notes: [docs/decisions.md](docs/decisions.md) (what was compared) and [docs/implementation.md](docs/implementation.md) (what was built).

## Evaluation

[`eval/run_eval.py`](eval/run_eval.py) runs 31 test requests against a saved Channel3 snapshot ([`eval/snapshot.json`](eval/snapshot.json)), so every version sees the same products. Run on 2026-11-12 with DeepSeek `deepseek-flash` at temperature 0; versions that call the model ran 3 times and are averaged. 24 requests are ranked (5 give no budget, 2 were not turned into a search).

| Version | Full top 3 | Hostile listings kept out | Top pick matches saved preference | Model calls per request |
| --- | --- | --- | --- | --- |
| Baseline: one search with the raw words | 17 / 24 | 0% | 0% | 0 |
| + multi-query search | 24 / 24 | 0% | 25% | 0 |
| + reasoning rank | 24 / 24 | 100% | 25% | 1 |
| + 3 shuffles | 24 / 24 | 100% | 25% | 3 |
| reasoning rank + budget filter | 24 / 24 | 100% | 25% | 1 |
| reasoning rank + memory | 4 / 4 | - | 50% | 1 |

- Every version stayed within budget and recommended only real search results, because the hard filter runs in code before ranking.
- Multi-query search fills the top 3; reasoning rank keeps hostile listings out (they are placed first, so search order alone always shows them); memory raised preference matches from 25% to 50% (4 requests, a small sample).
- 3 shuffles and the budget filter changed none of these numbers, and 3 shuffles cost three times the model calls.

More detail in [eval/README.md](eval/README.md).

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
