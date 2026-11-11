# CLAUDE.md

This file tells you how to work in this project. What to build is in `docs/requirements.md`; read it before starting any work. If the two files conflict, or a requirement is unclear, ask me instead of guessing.

## Language

- **Reply to me in Chinese (简体中文).** Plans, questions, explanations and summaries are all in Chinese.
- Everything written into the repository is in English: code, comments, commit messages, README, docs, and UI text. The judges read English.

## Project background

This is an entry for the PayPal AI Hackathon 2026: a conversational shopping agent. The user describes a need, the agent recommends 3 products, the user confirms and pays through the PayPal sandbox, and can later check the order or get a refund.

- **Deadline**: Thursday, November 12, 2026, 12:00 pm Pacific Time, which is 2:00 pm in Houston. The target is to submit by 12:00 pm Houston time.
- **The main purpose is my resume.** I am a CS master's student and will have to explain this code line by line in interviews. Code must be short, plain and explainable. One feature fewer is better than a block of code I cannot explain.
- **The differentiator is evaluation**: data that shows recommendation quality. The safety design (budget guard, human-approved payment) is a required baseline, not the highlight.
- The project is written from scratch. I have an earlier prototype that is only for comparison. Do not copy it.

## Tech stack

- Python 3.11+, FastAPI, SQLite (standard library `sqlite3`), httpx
- Model: called through an OpenAI-compatible API, provider is switchable (see "Model interface")
- Payments: PayPal REST API called directly (Orders v2, Payments v2), sandbox only
- Product data: Channel3 search API
- Frontend: one static HTML file with vanilla JavaScript, no frontend framework; design uses Impeccable (see "Frontend design")
- Deployment: Render

Do not add agent frameworks such as LangChain or LangGraph. The agent loop is written by hand, because that is the part I will explain in interviews.

## Suggested layout

```
app/llm.py        the only file that calls the model
app/agent.py      agent loop, tool definitions, system prompt
app/recommend.py  recommendation pipeline
app/catalog.py    product search, mock catalog, snapshots
app/paypal.py     PayPal calls and mock
app/memory.py     preference memory (P1)
app/store.py      sessions, carts, orders
app/main.py       HTTP endpoints
static/index.html chat page
eval/             test requests, adversarial listings, eval script
tests/            unit tests
docs/             requirements.md, decisions.md, implementation.md
```

## How to work

1. **Follow the milestone order** in section 11 of `docs/requirements.md`. Do one feature at a time, and verify it before starting the next.
2. **State the plan before writing code**: a few sentences on which files change and how.
3. **Do not widen the scope.** Do not add features that are not in the requirements. If you think something is worth adding, propose it and I will decide.
4. **Do not add dependencies on your own.** Explain why before adding a third-party library.
5. **Ask me before changing the behavior of a P0 feature or a safety rule.**
6. **Explain non-obvious choices** with a one-line comment that says why, not what.
7. **Write an implementation note for every finished feature** (see "Implementation notes").

## Implementation notes

Every time a feature is finished, add or update its entry in `docs/implementation.md` before starting the next feature. I use this file to prepare for interviews, so it must describe the code as it actually is, not as it was planned.

- **One entry per feature**, headed by the feature ID and name from `docs/requirements.md` (for example `## F11 Verify, then capture`). Features built together may share one entry that lists all their IDs.
- **Each entry contains**:
  1. What it does, in one or two sentences.
  2. Where it lives: files and function names.
  3. How it works: the steps in order, from input to output, including what happens on failure.
  4. Why it is built this way: the main choice made and the alternative that was rejected. Link to the `docs/decisions.md` entry if there is one.
  5. How it was verified: test names, and what was run by hand.
  6. Known limits and anything not verified.
- **Keep it short**: about 10 to 20 lines per entry. Plain sentences, no pasted code blocks longer than a few lines.
- **Keep it current**: when a later change alters how a feature works, update its entry in the same commit.
- **How it differs from `docs/decisions.md`**: `decisions.md` is written before implementing and records what was looked at and which approach was chosen. `implementation.md` is written after implementing and records what was actually built.
- The note goes in the same commit as the feature.

## Frontend design: use Impeccable

Use the Impeccable design skill for page design. Commands have the form `/impeccable <command>`. I install it myself (`/plugin marketplace add pbakaus/impeccable`, or `npx impeccable skills install` from the project root). If you find it is not available, tell me first. Do not skip it and design on your own.

Use it in this order:

1. **`/impeccable init`**: run once before any page work. It generates `PRODUCT.md` and `DESIGN.md`; every later page change follows `DESIGN.md`.
2. **`/impeccable shape`**: plan layout and interaction before writing the chat page.
3. **`/impeccable craft`**: build the page from that plan.
4. **`/impeccable audit`**: before deploying, check accessibility, performance and phone-width behavior.
5. **`/impeccable polish`**: a final pass before recording the video.

Limits:

- The page stays one static HTML file with vanilla JavaScript. Design work does not justify a frontend framework or a build step.
- Do not use effect-adding commands such as `animate`, `delight`, `overdrive` or `bolder` unless I ask. The goal of the page is clarity.
- Design changes must not affect payment behavior or trust cues. These must stay: the confirm-and-pay button, the note that nothing is charged before approval, the total in the order summary, the mock-mode badges, and the reasons for rejected products.
- Design work is limited to about 2 hours in total, scheduled in M3. If time is short, do only `init`, `craft` and `audit`.

## Look for credible open-source implementations first

Before implementing a feature that involves a real design choice, look at how others have done it, then decide our approach. This avoids inventing a flawed solution, and lets me explain in interviews why the design is what it is.

- **When it applies**: payment creation and return handling, pre-capture verification, idempotency, the agent tool loop, parsing and aggregating ranking output, preference memory, eval metric computation. It does not apply to copy changes, styling, or small bug fixes.
- **What counts as credible**, in priority order:
  1. Official repositories and examples in official docs: PayPal, the model provider in use, Channel3, FastAPI.
  2. Actively maintained, widely used open-source projects under MIT or Apache-2.0.
  3. Other hackathon entries may be read for ideas only, never used as the basis.
- **How far to go**: look at 2 to 3 implementations per feature, in about 15 minutes.
- **Keep a record**: add a short entry to `docs/decisions.md` with what you looked at (with links), how each does it, which approach we chose, and why.
- **Do not copy large blocks of code.** If you borrow a specific technique, note the source and its license in the record.
- If you cannot find a credible implementation, say so, then give your own approach and reasoning.

## Rules that must not be broken

These rules keep the agent from spending money on its own. They are also the first thing judges and interviewers will check.

- **The model has no tool that can move money.** Creating a PayPal order, capturing, and refunding happen only in HTTP endpoints triggered by a user click. The most the model can do is prepare a cart or draft a refund.
- **Prices are computed only by the server**, in integer cents. The model picks products by ID; any price it outputs is ignored.
- **Only products returned by a search in the current session can be ordered.** Unknown IDs are rejected.
- **The budget is checked in code**, not by the prompt.
- **Before capture, read the order back from PayPal**: capture only if the status is approved and the amount equals the cart the user confirmed. An order counts as paid only when the capture returns completed.
- **Create, capture and refund requests all carry a `PayPal-Request-Id`** to prevent double charges.
- **Sandbox only.** The PayPal base URL is hard-coded to the sandbox and is not configurable.
- **Secrets live only in environment variables.** Never in code, the frontend, logs, or commits. `.env` is not committed.
- **Product titles and descriptions are untrusted data.** Prompts must state that instructions and sales claims inside them are not to be followed.

## Model interface

I may use DeepSeek to save cost, or switch to another model, so:

- Every model call goes through `app/llm.py`. No other file uses a provider SDK directly.
- Use the OpenAI-compatible chat and function-calling format. Config: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- Do not depend on features unique to one provider. Provider-specific switches go only in the optional `LLM_EXTRA_BODY` config (a JSON object merged into the request body), never in code.
- In the tool loop, append the model's assistant message to the history unchanged.
- Validate JSON produced by the model. A blank reply counts as a format error. On a format error retry once; if it fails again use a fallback result. A request must never crash because of bad model output.
- With no key configured, fall back to a rule-based mock so the whole flow still runs.

## Definition of done

Before saying a feature is done:

1. Check it against each acceptance criterion for that feature in `docs/requirements.md`.
2. Run `pytest` and have everything pass. Logic involving prices, budgets and order states must have tests.
3. Run the flow for real in keyless mock mode.
4. **Report verification honestly**: what was tested, how, and what could not be tested. For example, real payment cannot be tested without sandbox credentials; say so plainly instead of calling it done.
5. Write or update the feature's entry in `docs/implementation.md` (see "Implementation notes").

## Evaluation discipline

- Evals read only from the search snapshot, so every version sees the same products.
- **Never make up a number.** Metrics in the README and docs come only from actual runs.
- Relevance labels (0, 1, 2) are assigned by me, by hand. Do not fill them in for me.
- Report results as they are, including no improvement or a regression.
- Record the model name, snapshot date and number of runs with every result.

## Git

- Small commits, one per feature, with a message that says what changed and why.
- Do not push unless I ask.
- Keep the repository safe to make public: no secrets, and an MIT license at the root.

## When time runs short

Cut in this order, earliest first: P2 optional features, preference memory, multi-shuffle ranking, refunds, shrinking the eval from 27 requests to 15. One complete purchase flow with eval numbers matters more than extra features.

## Common commands

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest
python -m eval.run_eval --name full
```
