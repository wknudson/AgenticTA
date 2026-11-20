"""Filing pipeline + library contract, fully offline (fake embeddings, heuristic labels).
Real-model quality is measured separately by evals/filing_eval.py."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agents.filing.pipeline import _clean_dates, _snap_unit, split_text
from app.shared import library
from app.shared.db import connect

BIO = 3  # "Biology Honors - Period 1" in the seed data


@pytest.fixture(scope="module")
def filed(client):
    out = client.post("/agents/filing/demo", params={"class_id": BIO}).json()
    return {f["original_name"]: f for f in out["files"]}


def test_demo_files_the_whole_sample_course(filed):
    assert len(filed) == 32
    assert sum(f["chunk_count"] > 0 for f in filed.values()) >= 29  # all but the 3 image-only files


def test_reupload_is_detected_as_duplicate(client, filed):
    again = client.post("/agents/filing/demo", params={"class_id": BIO}).json()
    assert again["filed"] == 0 and all(f["duplicate"] for f in again["files"])


def test_images_and_scans_without_a_key_go_to_review(filed):
    for name in ("organelle_matching_scan.png", "whiteboard_atp_cycle.jpg", "Unit4_Test_Genetics_scanned.pdf"):
        f = filed[name]
        assert f["status"] == "needs_review" and "GOOGLE_API_KEY" in f["review_reason"], name


def test_fast_labels_file_the_syllabus_without_any_ai(filed):
    f = library.get_file(filed["Bio10_Syllabus_Fall2026.docx"]["file_id"])
    assert (f.doc_type, f.unit, f.label_source, f.status) == ("syllabus", None, "auto", "filed")
    assert {d["date"] for d in f.dates} >= {"2026-09-17", "2026-10-15", "2026-12-16"}, "dates come from the table rows"


def test_file_name_rules_give_the_right_type(filed):
    want = {"Unit1_Quiz_Macromolecules.pdf": "quiz", "Lab_Report_Rubric.docx": "rubric", "Osmosis_Egg_Lab.pdf": "lab",
            "Final_Exam_Review_Guide.docx": "worksheet", "Course_Calendar_Fall2026.txt": "schedule",
            "Cell_Organelles_Slides.pptx": "lecture", "Reading_Endosymbiosis.txt": "reading"}
    assert {n: library.get_file(filed[n]["file_id"]).doc_type for n in want} == want


def test_unit_named_in_the_file_is_snapped_to_the_syllabus_unit(filed):
    f = library.get_file(filed["Unit2_Test_Systems.pdf" if "Unit2_Test_Systems.pdf" in filed else
                                "Unit 2 Test - Cell Structure.pdf"]["file_id"])
    assert f.unit == "Unit 2: Cell Structure"


def test_keyword_search_finds_exact_terms(client, filed):
    hits = client.get("/agents/filing/search", params={"class_id": BIO, "q": "toothpickase", "mode": "keyword"}).json()
    assert hits["results"][0]["file_id"] == filed["Enzyme_Lab_Toothpickase.pdf"]["file_id"]


def test_hybrid_search_fuses_both_retrievers(client, filed):
    res = client.get("/agents/filing/search", params={"class_id": BIO, "q": "Calvin cycle stroma"}).json()
    assert res["mode"] == "hybrid"
    top = res["results"][0]
    assert top["file_id"] == filed["Photosynthesis_Slides.pptx"]["file_id"] and top["match"] in ("both", "keyword")
    assert top["page"] is not None, "slide number is kept for PPTX hits"


def test_search_is_scoped_to_the_class(client, filed):
    assert client.get("/agents/filing/search", params={"class_id": 2, "q": "toothpickase"}).json()["results"] == []


def test_teacher_edit_files_it_and_marks_teacher_labels(client, filed):
    fid = filed["Bio10_Syllabus_Fall2026.docx"]["file_id"]
    out = client.patch(f"/agents/filing/files/{fid}", json={"unit": None, "title": "Course syllabus"}).json()
    assert out["status"] == "filed" and out["label_source"] == "teacher" and out["title"] == "Course syllabus"


def test_archive_hides_from_list_and_search_then_restore(client, filed):
    fid = filed["Reading_CRISPR_News.txt"]["file_id"]
    client.post(f"/agents/filing/files/{fid}/archive")
    assert fid not in [f["file_id"] for f in client.get("/agents/filing/files", params={"class_id": BIO}).json()["files"]]
    assert all(h["file_id"] != fid for h in
               client.get("/agents/filing/search", params={"class_id": BIO, "q": "CRISPR", "mode": "keyword"}).json()["results"])
    client.post(f"/agents/filing/files/{fid}/restore")
    assert library.get_file(fid).status == "filed"


def test_units_and_download(client, filed):
    units = client.get("/agents/filing/units", params={"class_id": BIO}).json()
    assert units["units"] and "syllabus" in units["doc_types"]
    fid = filed["Lab_Report_Rubric.docx"]["file_id"]
    r = client.get(f"/agents/filing/files/{fid}/download")
    assert r.status_code == 200 and r.content[:2] == b"PK"  # .docx is a zip


def test_chunks_written_by_other_agents_are_keyword_searchable(filed):
    """The FTS index is kept in sync by triggers, e.g. for the materials agent's drafts."""
    fid = filed["Lab_Safety_Contract.pdf"]["file_id"]
    with connect() as conn:
        conn.execute("INSERT INTO library_chunks (file_id, chunk_idx, text) VALUES (?, 99, 'zyxwvut marker phrase')", (fid,))
    assert library.search("zyxwvut", BIO, mode="keyword")


def test_split_text_respects_size_and_overlaps():
    text = " ".join(f"Sentence number {i} about cells." for i in range(200))
    chunks = split_text(text, size=300, overlap=60)
    assert len(chunks) > 5 and all(len(c) <= 300 for c in chunks)
    assert chunks[1][:40] in chunks[0], "each chunk starts with the end of the previous one"


def test_date_guardrail_drops_bad_and_far_dates():
    soon = (date.today() + timedelta(days=20)).isoformat()
    out = _clean_dates([{"date": soon, "label": "quiz"}, {"date": "2026-02-30", "label": "bad"},
                        {"date": "1999-01-01", "label": "old"}, {"date": soon, "label": "quiz"}])
    assert out == [{"date": soon, "label": "quiz"}]


def test_unit_guardrail_snaps_to_existing_names():
    existing = ["Unit 2: Cell Structure", "Unit 3: Cell Energy"]
    assert _snap_unit("unit 3 - energy", existing) == "Unit 3: Cell Energy"
    assert _snap_unit("UNIT 2: CELL STRUCTURE", existing) == "Unit 2: Cell Structure"
    assert _snap_unit("Unit 5: Ecology", existing) == "Unit 5: Ecology"
    assert _snap_unit("Unit 2: Cell Structure", ["Unit 2"]) == "Unit 2: Cell Structure", "more descriptive name wins"


def test_bare_unit_folder_is_renamed_when_a_better_name_arrives(filed):
    from app.agents.filing.pipeline import _upgrade_unit

    a, b = filed["Reading_Endosymbiosis.txt"]["file_id"], filed["Osmosis_Egg_Lab.pdf"]["file_id"]
    with connect() as conn:
        conn.execute("UPDATE library_files SET unit = 'Unit 9' WHERE file_id IN (?, ?)", (a, b))
    _upgrade_unit(BIO, "Unit 9: Ecology", ["Unit 9"])
    assert {library.get_file(a).unit, library.get_file(b).unit} == {"Unit 9: Ecology"}
