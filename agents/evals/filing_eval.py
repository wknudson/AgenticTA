"""Filing system evaluation: label accuracy + keyword vs semantic vs hybrid search.

    npm run eval:filing                      (local report only)
    npm run eval:filing -- --langsmith       (also logs 3 search experiments to LangSmith to compare)
    npm run eval:filing -- --search-only     (no labeling calls at all; just re-score search)
    npm run eval:filing -- --fresh           (start the eval library over; costs a full re-label)

Uses REAL models (filing agent's GOOGLE_API_KEY) on its own database in evals/.cache/, never
your dev data.

FREE-TIER FRIENDLY: the eval library is kept between runs.  Files that already have AI labels
are reused (0 calls); only new files and files that fell back to rules (because the daily quota
ran out) are sent to the AI again.  On the free tier (about 20 labeling calls/day) a full course
gets AI labels over a couple of days, and every run reports how many are still waiting.

Files the generated sample course (sample_data/biology_course), then grades:

  Labeling (vs sample_data/biology_course_key.json)
    type accuracy, unit accuracy, scans/photos read, how many went to review, time per file
  Search (vs sample_data/search_eval.json, 25 questions; results deduplicated to files)
    hit@1     the top result is a right file
    hit@5     a right file is somewhere in the top 5
    recall@5  share of the right files found in the top 5
    MRR       1 / rank of the first right file (1.0 = always first)
    split by question kind: 'paraphrase' (words not in the docs) vs 'exact' (words in the docs)

Writes evals/results/filing_eval_<timestamp>.md (+ .json) for the write-up.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import shutil
import time
from datetime import datetime
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
AGENTS = HERE.parent
REPO = AGENTS.parent
SAMPLE = AGENTS / "sample_data"
CLASS_ID = 3  # Biology Honors in the seed data
MODES = ("keyword", "semantic", "hybrid")


# gitignored: the eval's own library (db + saved originals).  Override only for offline checks.
CACHE = Path(os.getenv("AGENTICTA_EVAL_CACHE") or HERE / ".cache")


def open_eval_db(fresh: bool) -> None:
    """Point the app at evals/.cache/eval.sqlite, creating it (schema + seed) if needed."""
    db = CACHE / "eval.sqlite"
    if fresh and CACHE.exists():
        shutil.rmtree(CACHE)
    CACHE.mkdir(parents=True, exist_ok=True)
    os.environ["SQLITE_DB_PATH"] = str(db)
    if db.exists():
        return
    conn = sqlite3.connect(db)
    for name in ("schema.sql", "seed.sql"):
        conn.executescript((REPO / "backend" / "db" / name).read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


def course_order(names: list[str]) -> list[str]:
    """Syllabus and calendar first, so the labeler has the course outline for everything else."""
    return sorted(names, key=lambda n: (not any(w in n.lower() for w in ("syllabus", "calendar")), n))


def unit_no(u: str | None) -> str | None:
    import re
    m = re.search(r"unit\s*(\d+)", u or "", re.IGNORECASE)
    return m.group(1) if m else None


def file_ranking(query: str, mode: str) -> list[str]:
    from app.shared import library
    seen: list[str] = []
    for h in library.search(query, CLASS_ID, k=25, mode=mode):
        name = library.get_file(h.file_id).original_name
        if name not in seen:
            seen.append(name)
    return seen


def score(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    top5 = ranked[:5]
    first = next((i for i, n in enumerate(ranked, 1) if n in relevant), None)
    return {
        "hit@1": float(bool(ranked) and ranked[0] in relevant),
        "hit@5": float(any(n in relevant for n in top5)),
        "recall@5": sum(n in relevant for n in top5) / len(relevant),
        "mrr": 1.0 / first if first else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langsmith", action="store_true", help="also log search experiments to LangSmith")
    ap.add_argument("--search-only", action="store_true", help="make no labeling calls; score search on what's filed")
    ap.add_argument("--fresh", action="store_true", help="delete the eval library and label everything again")
    args = ap.parse_args()

    open_eval_db(args.fresh)
    sys.path.insert(0, str(AGENTS))
    from app.agents.filing import ai_queue
    from app.agents.filing.pipeline import AI_CALLS, ingest
    from app.shared import library
    from app.shared.db import connect, init_db
    from app.shared.embeddings import get_embedder
    from app.shared.llm import model_spec

    if get_embedder() is None:
        sys.exit("No GOOGLE_API_KEY for the filing agent (agents/app/agents/filing/.env). The eval needs real models.")
    init_db()

    # ---------------------------------------------------------------- filing + labels
    key = {k["file"]: k for k in json.loads((SAMPLE / "biology_course_key.json").read_text(encoding="utf-8"))}
    with connect() as conn:
        have = {r["original_name"]: dict(r) for r in conn.execute(
            "SELECT * FROM library_files WHERE class_id = ? AND status NOT IN ('archived', 'draft')", (CLASS_ID,))}
    t_all, ai_before = time.time(), AI_CALLS["requests"]
    how_by_name: dict[str, str] = {}
    for name in course_order(list(key)):
        prev = have.get(name)
        if prev or args.search_only:
            how_by_name[name] = "reused"  # already filed: costs nothing (the queue retries anything still pending)
        else:
            ingest(CLASS_ID, name, (SAMPLE / "biology_course" / name).read_bytes())
            how_by_name[name] = "new"
    if not args.search_only:  # the batched AI double-check, as the background worker would do it
        ai_queue.process_pending(CLASS_ID, force=True, until_empty=True)
    ai_requests = AI_CALLS["requests"] - ai_before

    with connect() as conn:
        current = {r["original_name"]: dict(r) for r in conn.execute(
            "SELECT * FROM library_files WHERE class_id = ? AND status NOT IN ('archived', 'draft')", (CLASS_ID,))}
    rows = []
    for name in course_order(list(key)):
        r, how, t = current.get(name), how_by_name.get(name, "-"), time.time()
        if r is None:
            continue
        k = key[name]
        rows.append({
            "file": name, "how": how, "seconds": round(time.time() - t, 1),
            "type": r["doc_type"], "type_ok": r["doc_type"] in k["doc_types"],
            "unit": r["unit"], "unit_ok": unit_no(r["unit"]) == unit_no(k["unit"]),
            "status": r["status"], "reason": r["review_reason"], "source": r["label_source"],
            "needs_vision": k["needs_vision"], "read_ok": (not k["needs_vision"]) or r["extract_method"] == "vision",
        })
        print(f"  {'ok ' if rows[-1]['type_ok'] and rows[-1]['unit_ok'] else 'MISS'} {how:7} {name:45} "
              f"{r['doc_type']:9} {str(r['unit']):38} {r['label_source']}")
    if not rows:
        sys.exit("Nothing filed yet: run without --search-only first.")
    ai_rows = [r for r in rows if r["source"] in ("llm", "llm-fallback")]
    auto_rows = [r for r in rows if r["source"] == "auto"]
    labeling = {
        "files": len(rows),
        "ai_requests_this_run": ai_requests,
        "labeled_without_ai": f"{len(auto_rows)}/{len(rows)}",
        "labeled_by_ai": f"{len(ai_rows)}/{len(rows)}",
        "still_waiting_for_ai": sum(bool(current[r['file']]["ai_pending"]) for r in rows),
        "accuracy_without_ai": mean(r["type_ok"] and r["unit_ok"] for r in auto_rows) if auto_rows else 0.0,
        "accuracy_ai_labeled": mean(r["type_ok"] and r["unit_ok"] for r in ai_rows) if ai_rows else 0.0,
        "type_accuracy": mean(r["type_ok"] for r in rows),
        "unit_accuracy": mean(r["unit_ok"] for r in rows),
        "both_correct": mean(r["type_ok"] and r["unit_ok"] for r in rows),
        "vision_files_read": f"{sum(r['read_ok'] for r in rows if r['needs_vision'])}/{sum(r['needs_vision'] for r in rows)}",
        "sent_to_review": sum(r["status"] == "needs_review" for r in rows),
        "used_fallback_model": sum(r["source"] == "llm-fallback" for r in rows),
        "seconds_this_run": round(time.time() - t_all, 1),
    }
    # The search part below makes only embedding calls (one per question per mode), not labeling calls.
    library.reindex(CLASS_ID)  # embed anything that missed its embeddings earlier (e.g. per-minute limit)

    # ---------------------------------------------------------------- search
    queries = json.loads((SAMPLE / "search_eval.json").read_text(encoding="utf-8"))["queries"]
    search: dict[str, dict] = {}
    per_query = []
    for mode in MODES:
        scores = []
        for q in queries:
            ranked = file_ranking(q["q"], mode)
            s = score(ranked, q["relevant"])
            scores.append((q["kind"], s))
            per_query.append({"mode": mode, "q": q["q"], "kind": q["kind"], "top3": ranked[:3], **s})
        search[mode] = {
            kind: {m: round(mean(s[m] for k_, s in scores if kind in ("all", k_)), 3) for m in ("hit@1", "hit@5", "recall@5", "mrr")}
            for kind in ("all", "paraphrase", "exact")
        }

    # ---------------------------------------------------------------- report
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    models = {role: model_spec("filing", role)["model"] for role in ("labeler", "labeler_fallback")}
    lines = [
        f"# Filing eval {stamp}", "",
        f"Models: labeler `{models['labeler']}`, fallback `{models['labeler_fallback']}`, embeddings `{get_embedder().model}`.",
        f"Sample course: {labeling['files']} files. Search: {len(queries)} questions.", "",
        "## Labeling", "",
        "| metric | value |", "|---|---|",
        *[f"| {k} | {v:.0%} |" if ("accuracy" in k or k.endswith("correct")) else f"| {k} | {v} |"
          for k, v in labeling.items()], "",
        "## Search (file level)", "",
        "| mode | questions | hit@1 | hit@5 | recall@5 | MRR |", "|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        for kind in ("all", "paraphrase", "exact"):
            m = search[mode][kind]
            lines.append(f"| {mode} | {kind} | {m['hit@1']:.2f} | {m['hit@5']:.2f} | {m['recall@5']:.2f} | {m['mrr']:.2f} |")
    misses = [r for r in rows if not (r["type_ok"] and r["unit_ok"])]
    lines += ["", "## Labeling misses", ""] + ([f"- `{r['file']}`: got {r['type']} / {r['unit']}" for r in misses] or ["None"])
    (out_dir / f"filing_eval_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / f"filing_eval_{stamp}.json").write_text(json.dumps(
        {"labeling": labeling, "search": search, "files": rows, "queries": per_query, "models": models}, indent=2), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nSaved evals/results/filing_eval_{stamp}.md")

    if args.langsmith:
        log_to_langsmith(queries)


def log_to_langsmith(queries: list[dict]) -> None:
    """One dataset, three experiments (keyword / semantic / hybrid) to compare side by side."""
    from langsmith import Client, evaluate

    from app.shared.settings import langsmith_enabled
    from app.shared.tracing import project_name

    if not langsmith_enabled():
        print("LangSmith not configured (project .env); skipped.")
        return
    client, name = Client(), "agentic-ta-filing-search"
    if not client.has_dataset(dataset_name=name):
        ds = client.create_dataset(name, description="Sample Biology Honors course search questions (filing eval)")
        client.create_examples(dataset_id=ds.id, examples=[
            {"inputs": {"q": q["q"]}, "outputs": {"relevant": q["relevant"]}, "metadata": {"kind": q["kind"]}} for q in queries])

    def evaluator(metric: str):
        def ev(outputs: dict, reference_outputs: dict) -> dict:
            files = (outputs or {}).get("files", [])  # a failed target run scores 0, not an error
            return {"key": metric, "score": score(files, reference_outputs["relevant"])[metric]}
        ev.__name__ = metric.replace("@", "_at_")
        return ev

    for mode in MODES:
        evaluate(lambda inputs, m=mode: {"files": file_ranking(inputs["q"], m)[:5]}, data=name,
                 evaluators=[evaluator(k) for k in ("hit@1", "hit@5", "recall@5", "mrr")],
                 experiment_prefix=f"search-{mode}", metadata={"mode": mode, "project": project_name("filing")},
                 client=client, max_concurrency=1)  # sequential: free-tier embeddings allow 100 requests/minute
    print(f"Logged 3 experiments to LangSmith dataset '{name}' (Datasets & Experiments > compare).")


if __name__ == "__main__":
    main()
