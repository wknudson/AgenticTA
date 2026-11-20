"""Scorecard: compare what the Library filed with the answer key in test_materials/expected.json.

    npm run test-materials:check                 Algebra II (class 1) + Intro to CS (class 4)
    npm run test-materials:check -- --class 4    one class

Shows each file's type/unit vs. the expected ones, who labeled it (auto = rules + embeddings,
AI, you), anything still waiting for the AI, and the totals.  Read-only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.shared.db import connect  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CLASS_FOLDERS = {1: ("algebra2", "edge_cases"), 4: ("intro_cs",)}


def unit_no(u: str | None) -> str | None:
    m = re.search(r"unit\s*(\d+)", u or "", re.IGNORECASE)
    return m.group(1) if m else None


def check(class_id: int, expected: list[dict]) -> tuple[int, int]:
    want = {e["file"]: e for e in expected if e["folder"] in CLASS_FOLDERS.get(class_id, ())}
    with connect() as conn:
        name = conn.execute("SELECT class_name FROM classes WHERE class_id = ?", (class_id,)).fetchone()[0]
        rows = {r["original_name"]: dict(r) for r in conn.execute(
            "SELECT * FROM library_files WHERE class_id = ? AND status NOT IN ('archived', 'draft')", (class_id,))}
    print(f"\n{name} (class {class_id}): {len(rows)} filed, {len(want)} in the answer key")
    ok = total = 0
    sources: dict[str, int] = {}
    for fname, e in sorted(want.items()):
        r = rows.get(fname)
        if r is None:
            if "(1)" not in fname:  # the duplicate is expected NOT to be filed
                print(f"  --    {fname:44} not uploaded yet")
            continue
        total += 1
        type_ok = r["doc_type"] in e["doc_types"]
        unit_ok = unit_no(r["unit"]) == unit_no(e["unit"])
        ok += type_ok and unit_ok
        src = "WAITING" if r["ai_pending"] else (r["label_source"] or "?")
        sources[src] = sources.get(src, 0) + 1
        mark = "ok  " if type_ok and unit_ok else "MISS"
        got = f"{r['doc_type']} / {r['unit'] or 'whole course'}"
        exp = "" if type_ok and unit_ok else f"   expected {'|'.join(e['doc_types'])} / {e['unit'] or 'whole course'}"
        print(f"  {mark}  {fname:44} {got:48} [{src}]{exp}")
    if total:
        print(f"  => {ok}/{total} right ({ok / total:.0%}). Labeled by: {sources}")
    return ok, total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="class_id", type=int, choices=sorted(CLASS_FOLDERS))
    args = ap.parse_args()
    expected = json.loads((REPO / "test_materials" / "expected.json").read_text(encoding="utf-8"))
    for cid in ([args.class_id] if args.class_id else sorted(CLASS_FOLDERS)):
        check(cid, expected)


if __name__ == "__main__":
    main()
