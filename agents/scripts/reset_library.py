"""Empty the Library (filed documents) without touching anything else in the database.

    npm run library:reset                 every class
    npm run library:reset -- --class 1    just one class (1 = Algebra II, 3 = Biology, 4 = Intro to CS)

Removes library_files, their chunks, the keyword and vector index entries, and the saved
originals in data/files/.  Accounts, classes, assignments, grades, approvals and calendar
events stay.  Safe to run while `npm run dev` is running.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.shared import library  # noqa: E402
from app.shared.db import connect, init_db  # noqa: E402
from app.shared.settings import DB_PATH, FILES_DIR  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--class", dest="class_id", type=int, help="only this class id")
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit("No database yet. Run `npm run setup` first.")
    init_db()
    where, params = ("WHERE class_id = ?", (args.class_id,)) if args.class_id else ("", ())
    with connect() as conn:
        ids = [r[0] for r in conn.execute(f"SELECT file_id FROM library_files {where}", params).fetchall()]
        for fid in ids:
            library.delete_chunks(fid, conn)
        conn.execute(f"DELETE FROM library_files {where}", params)  # one statement, so versions go with their originals
    folders = [FILES_DIR / str(args.class_id)] if args.class_id else [p for p in FILES_DIR.glob("*") if p.is_dir()]
    for folder in folders:
        if folder.is_dir():
            shutil.rmtree(folder)
    print(f"Removed {len(ids)} filed document(s)" + (f" from class {args.class_id}" if args.class_id else " from every class") + ".")


if __name__ == "__main__":
    main()
