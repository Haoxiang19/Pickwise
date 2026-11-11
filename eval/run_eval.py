"""Eval runner. Usage: python -m eval.run_eval --name full [--runs 3]

1. Load the test requests, the hostile listings and the human labels.
2. Load the search snapshot, or build it on the first run (step 1 output + search results); never change it after.
3. Ask accuracy: run step 1 live on every test request, with no search.
4. Replay the snapshot through steps 2-5 for each ablation version, log every request.
5. Print the metrics table and save logs, a summary and the list of products still to label.
"""
import argparse
import datetime
import json
import os
import time
from pathlib import Path

from app import agent, catalog, llm, recommend as rec
from app.money import to_dollars
from eval import metrics

EVAL_DIR = Path(__file__).parent
VERSIONS = [
    ("baseline", {"multi_query": False, "reasoning_rank": False}),
    ("+ multi-query search", {"multi_query": True, "reasoning_rank": False}),
    ("+ reasoning rank", {"multi_query": True, "reasoning_rank": True}),
]
SEEDS = [101, 202, 303]  # one shuffle seed per run
RANKED_TYPES = ("clear", "gift", "adversarial")  # missing-budget requests are only used for ask accuracy


def load(name: str):
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


def hostile_listings() -> dict[str, list[dict]]:
    """Adversarial listings completed to the Product shape, by request ID."""
    data = load("adversarial.json")
    base = {"currency": "USD", "in_stock": True, "url": "", "image": "", "category": ""}
    return {rid: [{**base, **p} for p in items] for rid, items in data.items() if not rid.startswith("_")}


# --- Snapshot ---

def snapshot_path() -> Path:
    # A snapshot built with a mock model or mock catalog must never be mistaken for the real one.
    return EVAL_DIR / ("snapshot.json" if llm.enabled() and catalog.enabled() else "snapshot_mock.json")


def build_snapshot(requests: list[dict]) -> dict:
    snap = {"created": datetime.date.today().isoformat(),
            "catalog": "channel3" if catalog.enabled() else "mock",
            "step1_model": os.getenv("LLM_MODEL") if llm.enabled() else "mock",
            "requests": {}}
    for item in requests:
        if item["type"] not in RANKED_TYPES:
            continue
        step1 = agent.understand(item["text"])
        entry = {"step1": step1, "raw_results": catalog.search(item["text"], rec.SEARCH_LIMIT)}
        if "request" in step1:
            entry["results"] = {q: catalog.search(q, rec.SEARCH_LIMIT) for q in step1["request"]["queries"]}
        snap["requests"][item["id"]] = entry
    return snap


def load_snapshot(requests: list[dict]) -> tuple[dict, Path]:
    path = snapshot_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), path
    snap = build_snapshot(requests)
    path.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    return snap, path


# --- Runs ---

def ask_accuracy(requests: list[dict]) -> dict:
    """Step 1 live on every request: did the agent ask exactly when the budget was missing?"""
    llm.reset_usage()
    rows = []
    for item in requests:
        out = agent.understand(item["text"])
        asked = "ask" in out
        rows.append({"request_id": item["id"], "expect_ask": item["expect_ask"], "asked": asked,
                     "correct": asked == item["expect_ask"], "error": out.get("error")})
    return {"accuracy": metrics.mean([1.0 if r["correct"] else 0.0 for r in rows]), "rows": rows, "usage": dict(llm.usage)}


def run_one(item: dict, entry: dict, version: str, flags: dict, seed: int, injected: list[dict]) -> dict:
    """Replay one request through steps 2-5 and compute its per-request metrics."""
    request = entry["step1"]["request"]
    if flags["multi_query"]:
        results = entry["results"]
    else:
        request = {**request, "raw_request": item["text"]}  # baseline: one search with the user's raw words
        results = {item["text"]: entry["raw_results"]}
    for p in injected:
        if not metrics.meets_constraints(p, request):
            raise ValueError(f"{p['id']} would be removed by the hard filter, so it would test nothing")

    llm.reset_usage()
    start = time.perf_counter()
    out = rec.recommend(request, flags, lambda q, limit: results.get(q, [])[:limit], seed=seed, inject=injected)
    seconds = time.perf_counter() - start

    # Ground truth for grounding: the snapshot results themselves, not the pipeline's own copies.
    pool = {p["id"]: p for products in results.values() for p in products} | {p["id"]: p for p in injected}
    recs = out["recommendations"]
    hostile_ids = {p["id"] for p in injected}
    return {
        "request_id": item["id"], "type": item["type"], "version": version, "seed": seed,
        "queries": out["queries"],
        "candidates": [p["id"] for p in out["candidates"]],
        "rejected": [[r["id"], r["reason"]] for r in out["rejected"]],
        "ranking": [r["id"] for r in out["ranking"]],
        "recommended": [{"id": r["id"], "title": r["title"], "price_cents": r["price_cents"], "reason": r["reason"]} for r in recs],
        "constraint_ok": [pool.get(r["id"]) is not None and metrics.meets_constraints(pool[r["id"]], request) for r in recs],
        "grounded": [metrics.is_grounded(r, pool) for r in recs],
        "over_budget": sum(metrics.is_over_budget(pool[r["id"]], request) for r in recs if r["id"] in pool),
        "hostile_in_top3": [r["id"] for r in recs if r["id"] in hostile_ids],
        "seconds": seconds,
        "model_calls": llm.usage["calls"],
        "tokens": llm.usage["prompt_tokens"] + llm.usage["completion_tokens"],
    }


# --- Summary ---

def share(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def summarize(logs: list[dict], labels: dict) -> list[dict]:
    """One row per version and request type. Each metric is computed per run, then averaged over runs."""
    rows = []
    for version, _ in VERSIONS:
        for typ in RANKED_TYPES + ("all",):
            selected = [l for l in logs if l["version"] == version and typ in ("all", l["type"])]
            if not selected:
                continue
            runs = [[l for l in selected if l["seed"] == s] for s in sorted({l["seed"] for l in selected})]

            def per_run(fn):
                return metrics.mean([fn(run) for run in runs])

            ndcg = [[metrics.ndcg_at_3([r["id"] for r in l["recommended"]], labels.get(l["request_id"], {})) for l in run]
                    for run in runs]
            adversarial = typ in ("adversarial", "all")
            rows.append({
                "version": version, "type": typ, "requests": len(runs[0]), "runs": len(runs),
                "constraint_satisfaction": per_run(lambda run: share([ok for l in run for ok in l["constraint_ok"]])),
                "grounding": per_run(lambda run: share([ok for l in run for ok in l["grounded"]])),
                "over_budget": per_run(lambda run: sum(l["over_budget"] for l in run)),
                "injection_resistance": per_run(lambda run: share([not l["hostile_in_top3"] for l in run if l["type"] == "adversarial"]))
                if adversarial else None,
                "ndcg@3": metrics.mean([metrics.mean(scores) for scores in ndcg]),
                "ndcg_incomplete": sum(1 for scores in zip(*ndcg) if any(s is None for s in scores)),
                "seconds": per_run(lambda run: metrics.mean([l["seconds"] for l in run])),
                "model_calls": per_run(lambda run: metrics.mean([l["model_calls"] for l in run])),
                "tokens": per_run(lambda run: metrics.mean([l["tokens"] for l in run])),
            })
    return rows


def to_label(logs: list[dict], labels: dict, requests: list[dict]) -> dict:
    """Pooling: every product some version recommended that has no label yet, grouped by request."""
    texts = {r["id"]: r["text"] for r in requests}
    pending = {}
    for l in logs:
        for r in l["recommended"]:
            if labels.get(l["request_id"], {}).get(r["id"]) is None:
                entry = pending.setdefault(l["request_id"], {"request": texts[l["request_id"]], "products": {}})
                entry["products"][r["id"]] = {"title": r["title"], "price": f"${to_dollars(r['price_cents'])}", "label": None}
    return pending


def fmt(value, pct=False) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%" if pct else f"{value:.2f}"


def print_table(meta: dict, rows: list[dict], ask: dict) -> None:
    for key, value in meta.items():
        print(f"{key}: {value}")
    print(f"ask accuracy (live step 1, {len(ask['rows'])} requests): {fmt(ask['accuracy'], pct=True)}")
    header = ["version", "type", "n", "runs", "constraints", "grounding", "over-budget", "injection", "NDCG@3", "unlabeled", "sec", "calls", "tokens"]
    print(" | ".join(header))
    for r in rows:
        print(" | ".join([r["version"], r["type"], str(r["requests"]), str(r["runs"]),
                          fmt(r["constraint_satisfaction"], True), fmt(r["grounding"], True), fmt(r["over_budget"]),
                          fmt(r["injection_resistance"], True), fmt(r["ndcg@3"]), str(r["ndcg_incomplete"]),
                          fmt(r["seconds"]), fmt(r["model_calls"]), fmt(r["tokens"])]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the recommendation eval.")
    parser.add_argument("--name", required=True, help="output folder under eval/runs/")
    parser.add_argument("--runs", type=int, default=3, choices=[1, 2, 3], help="runs for versions that call the model")
    args = parser.parse_args()

    requests, hostile, labels = load("requests.json"), hostile_listings(), load("labels.json")
    snapshot, snap_path = load_snapshot(requests)
    ask = ask_accuracy(requests)

    logs, skipped = [], []
    for version, flags in VERSIONS:
        # Without reasoning rank no model is called after step 1, so the result is the same every time: one run.
        seeds = SEEDS[:args.runs] if flags["reasoning_rank"] else SEEDS[:1]
        for seed in seeds:
            for item in requests:
                if item["type"] not in RANKED_TYPES:
                    continue
                entry = snapshot["requests"][item["id"]]
                if "request" not in entry["step1"]:
                    skipped.append({"request_id": item["id"], "version": version, "step1": entry["step1"]})
                    continue
                logs.append(run_one(item, entry, version, flags, seed, hostile.get(item["id"], [])))

    mock = [name for name, on in (("model", llm.enabled()), ("catalog", catalog.enabled())) if not on]
    meta = {
        "WARNING": f"mock {', '.join(mock)}: these numbers are not results" if mock else "none",
        "ranking model": os.getenv("LLM_MODEL") if llm.enabled() else "mock",
        "step 1 model (snapshot)": snapshot["step1_model"],
        "catalog (snapshot)": snapshot["catalog"],
        "snapshot": f"{snap_path.name}, created {snapshot['created']}",
        "runs (versions with reasoning rank)": args.runs,
        "temperature": llm.DEFAULT_TEMPERATURE,
        "shuffle seeds": SEEDS[:args.runs],
        "skipped (step 1 did not produce a request)": sorted({s["request_id"] for s in skipped}) or "none",
    }
    rows = summarize(logs, labels)

    out_dir = EVAL_DIR / "runs" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs.jsonl").write_text("".join(json.dumps(l) + "\n" for l in logs), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "ask": ask, "rows": rows, "skipped": skipped}, indent=1), encoding="utf-8")
    (out_dir / "to_label.json").write_text(json.dumps(to_label(logs, labels, requests), indent=1), encoding="utf-8")
    print_table(meta, rows, ask)
    print(f"\nSaved to {out_dir}. Products still to label: {out_dir / 'to_label.json'}")


if __name__ == "__main__":
    main()
