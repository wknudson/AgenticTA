"""Fake class materials for testing the Library by hand (drag them into the drop zone).

    npm run test-materials

Writes AgenticTA/test_materials/:
  algebra2/     18 files for "Algebra II - Period 2"   (log in as sarah_b)
  intro_cs/     12 files for "Intro to CS - Period 6"  (also sarah_b)
  edge_cases/    6 tricky files to drop into Algebra II (duplicate, new version, spreadsheet,
                 blank scan, sticky-note photo, 8-page textbook excerpt)
  expected.json  the right type/unit for each file, so you can check the labels

Everything is invented (names, dates, students).  Dates are in the Fall 2026 term.
Many files never say which unit they belong to on purpose: the labeler has to work it out
from the syllabus outline, so upload each class's syllabus first.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from build_sample_course import render_page, write_docx, write_pdf, write_pptx
from fpdf import FPDF

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "test_materials"

A1, A2, A3, A4 = ("Unit 1: Linear Functions", "Unit 2: Systems of Equations",
                  "Unit 3: Quadratic Functions", "Unit 4: Exponential Functions")
C1, C2, C3 = ("Unit 1: Getting Started with Python", "Unit 2: Decisions and Loops", "Unit 3: Functions and Lists")

FILES: list[dict] = []


def add(folder: str, name: str, types, unit, content, kind: str | None = None, note: str = "") -> None:
    FILES.append({"folder": folder, "name": name, "types": [types] if isinstance(types, str) else types,
                  "unit": unit, "content": content, "kind": kind or Path(name).suffix.lower().lstrip("."), "note": note})


# =================================================================== Algebra II
ALG = "algebra2"
add(ALG, "Algebra2_Syllabus_Fall2026.docx", "syllabus", None, [
    ("h", "Algebra II (Period 2) Syllabus, Fall 2026"),
    ("p", "Teacher: Ms. Sarah Bennett. Room 101. Office hours Tuesday and Thursday after school."),
    ("h", "Units"),
    ("p", "Unit 1: Linear Functions (Aug 24 to Sep 18). Slope, slope-intercept and point-slope form, graphing lines, parallel and perpendicular lines."),
    ("p", "Unit 2: Systems of Equations (Sep 21 to Oct 16). Solving by graphing, substitution, and elimination; word problems; systems of inequalities."),
    ("p", "Unit 3: Quadratic Functions (Oct 19 to Nov 13). Parabolas, vertex form, factoring, the quadratic formula, the discriminant."),
    ("p", "Unit 4: Exponential Functions (Nov 16 to Dec 11). Growth and decay, compound interest, exponent rules."),
    ("h", "Key dates"),
    ("table", [["Date", "Event"], ["2026-09-16", "Unit 1 quiz"], ["2026-10-14", "Unit 2 test"],
               ["2026-11-11", "Unit 3 quiz"], ["2026-12-09", "Compound interest project due"], ["2026-12-15", "Final exam"]]),
    ("h", "Grading"),
    ("p", "Tests 45%, quizzes 25%, homework 20%, project 10%. Show your work: answers without work earn half credit."),
    ("p", "Calculators: scientific calculators only on quizzes. Graphing calculators allowed on the project."),
])
add(ALG, "Algebra2_Calendar_Fall2026.txt", "schedule", None,
    "ALGEBRA II CALENDAR, FALL 2026 (Period 2)\n\n2026-08-24  First day\n2026-09-16  Unit 1 quiz (linear functions)\n"
    "2026-10-14  Unit 2 test (systems)\n2026-10-30  Quadratic formula discovery activity\n2026-11-11  Unit 3 quiz (quadratics)\n"
    "2026-11-25 to 2026-11-27  Thanksgiving break\n2026-12-09  Compound interest project due\n2026-12-15  Final exam\n")
add(ALG, "Unit1_Slope_and_Lines_Slides.pptx", "lecture", A1, [
    ("Unit 1: Linear Functions", "Slope and lines"),
    ("What is slope?", "Slope = rise over run = (y2 - y1) / (x2 - x1)\nPositive slope goes up to the right; negative goes down."),
    ("Slope-intercept form", "y = mx + b\nm is the slope, b is the y-intercept."),
    ("Parallel and perpendicular", "Parallel lines have equal slopes.\nPerpendicular slopes are negative reciprocals: 2 and -1/2."),
])
add(ALG, "slope_intercept_notes.txt", "lecture", A1,
    "Notes: point-slope form\n\nIf you know one point (x1, y1) and the slope m, write y - y1 = m(x - x1).\n"
    "Example: through (2, 5) with slope 3: y - 5 = 3(x - 2), so y = 3x - 1.\n"
    "Converting to standard form Ax + By = C: move the x term over and clear fractions.\n",
    note="never names its unit; the syllabus outline should place it in Unit 1")
add(ALG, "Graphing_Lines_Worksheet.docx", "worksheet", A1, [
    ("h", "Worksheet: Graphing Lines"),
    ("p", "1. Graph y = 2x - 3. Label the y-intercept."),
    ("p", "2. Find the slope through (1, 4) and (5, 12)."),
    ("p", "3. Write the equation of the line parallel to y = -x + 6 through (0, 2)."),
    ("p", "4. Are y = 3x + 1 and y = -1/3 x + 4 perpendicular? Explain."),
])
add(ALG, "Unit 1 Quiz - Linear Functions.pdf", "quiz", A1,
    "UNIT 1 QUIZ: LINEAR FUNCTIONS   Date: 2026-09-16\n\n1. Find the slope between (-2, 3) and (4, -9).\n"
    "2. Write y - 4 = 2(x + 1) in slope-intercept form.\n3. Give the slope of any line perpendicular to y = 5x - 2.\n"
    "4. A taxi charges $3 plus $2 per mile. Write and graph the cost function.")
add(ALG, "Systems_Substitution_Elimination_Notes.docx", "lecture", A2, [
    ("h", "Notes: solving systems by substitution and elimination"),
    ("p", "Substitution: solve one equation for a variable, then plug it into the other equation."),
    ("p", "Elimination: add or subtract the equations (after multiplying if needed) so one variable cancels."),
    ("p", "One solution means the lines cross. No solution: parallel lines. Infinitely many: the same line."),
], note="never names its unit")
add(ALG, "Systems_Word_Problems_Practice.pdf", "worksheet", A2,
    "PRACTICE: SYSTEMS WORD PROBLEMS\n\n1. Movie tickets cost $8 for students and $12 for adults. 40 tickets sold for $400. How many of each?\n"
    "2. A boat goes 24 miles downstream in 2 hours and back in 3 hours. Find the boat's speed and the current.\n"
    "3. Mix a 10% salt solution with a 30% solution to make 20 liters of 25% solution.")
add(ALG, "Unit2_Test_Systems.pdf", "test", A2,
    "UNIT 2 TEST: SYSTEMS OF EQUATIONS   Date: 2026-10-14\n\nPart A: Solve by substitution: y = 2x + 1 and 3x + y = 11.\n"
    "Part B: Solve by elimination: 2x + 3y = 12 and 4x - 3y = 6.\nPart C: Graph the system of inequalities y > x - 2 and y <= -x + 4.\n"
    "Part D: Word problem: two numbers add to 30 and differ by 8. Find them.")
add(ALG, "Quadratics_Slides.pptx", "lecture", A3, [
    ("Unit 3: Quadratic Functions", "Parabolas"),
    ("Standard and vertex form", "Standard: y = ax^2 + bx + c\nVertex form: y = a(x - h)^2 + k, vertex at (h, k)"),
    ("The discriminant", "b^2 - 4ac > 0: two real roots\n= 0: one real root\n< 0: no real roots"),
    ("The quadratic formula", "x = (-b +/- sqrt(b^2 - 4ac)) / (2a)"),
])
add(ALG, "Factoring_Practice_Worksheet.docx", "worksheet", A3, [
    ("h", "Factoring practice"),
    ("p", "Factor completely: 1) x^2 + 7x + 12   2) x^2 - 9   3) 2x^2 + 5x - 3   4) x^2 - 10x + 25"),
    ("p", "5) Solve by factoring: x^2 - x - 20 = 0."),
], note="never names its unit")
add(ALG, "Quadratic_Formula_Discovery_Activity.pdf", ["worksheet", "lab"], A3,
    "ACTIVITY: DISCOVERING THE QUADRATIC FORMULA   Date: 2026-10-30\n\nIn pairs, complete the square on ax^2 + bx + c = 0 step by step. "
    "Each step is on a card; put the cards in order and justify each move. Then use your formula on 2x^2 + 3x - 2 = 0 "
    "and check with factoring.")
add(ALG, "whiteboard_vertex_form.jpg", "lecture", A3,
    ["VERTEX FORM  y = a(x - h)^2 + k", "", "vertex = (h, k)", "a > 0 opens UP,  a < 0 opens DOWN",
     "example: y = 2(x - 3)^2 + 1  -> vertex (3, 1)", "", "axis of symmetry: x = h"], kind="photo",
    note="photo of a whiteboard: needs Gemini vision")
add(ALG, "Unit3_Quiz_Quadratics_SCANNED.pdf", "quiz", A3,
    ["UNIT 3 QUIZ: QUADRATICS", "Date: 2026-11-11       Name: ____________", "",
     "1. Find the vertex of y = (x + 2)^2 - 5.", "2. Factor x^2 + 2x - 15.", "3. Use the discriminant: how many roots",
     "   does x^2 + 4x + 9 = 0 have?", "4. Solve 3x^2 - 12 = 0."], kind="scan",
    note="scanned PDF with no text layer: needs Gemini vision")
add(ALG, "Exponential_Growth_Notes.md", "lecture", A4,
    "# Exponential growth and decay\n\nGrowth: y = a(1 + r)^t. Decay: y = a(1 - r)^t.\n\n"
    "- a is the starting amount, r is the rate as a decimal, t is time.\n- Doubling time: about 70 / (percent rate) years.\n"
    "- Compound interest: A = P(1 + r/n)^(nt).\n", note="never names its unit")
add(ALG, "Compound_Interest_Project_Rubric.docx", "rubric", A4, [
    ("h", "Compound Interest Project Rubric (due 2026-12-09)"),
    ("table", [["Criterion", "4", "2", "0"], ["Correct formula and setup", "All correct", "Minor errors", "Missing"],
               ["Comparison of 3 savings plans", "Clear table and graph", "Incomplete", "Missing"],
               ["Written recommendation", "Uses the math to justify", "Opinion only", "Missing"]]),
])
add(ALG, "Reading_Why_Credit_Card_Debt_Grows.txt", "reading", A4,
    "Reading: why credit card debt grows so fast\n\nA card with 24% yearly interest compounded monthly charges about 2% a month. "
    "If you owe $1,000 and pay nothing, after one year you owe about $1,268, and after five years over $3,000. "
    "That is exponential growth working against you. Paying only the minimum keeps the balance growing for years.")
add(ALG, "Final_Review_Algebra2.docx", ["worksheet", "other"], None, [
    ("h", "Final exam review (2026-12-15)"),
    ("p", "Lines: slope, forms of a line, parallel/perpendicular. Systems: all three methods."),
    ("p", "Quadratics: vertex form, factoring, quadratic formula. Exponentials: growth, decay, compound interest."),
])

# =================================================================== Intro to CS
CS = "intro_cs"
add(CS, "IntroCS_Syllabus.docx", "syllabus", None, [
    ("h", "Intro to Computer Science (Period 6), Fall 2026"),
    ("p", "Teacher: Ms. Sarah Bennett. Lab A. We write Python in the browser-based editor."),
    ("p", "Unit 1: Getting Started with Python (Aug 24 to Sep 25). Printing, variables, input, data types."),
    ("p", "Unit 2: Decisions and Loops (Sep 28 to Oct 30). If statements, while and for loops, debugging."),
    ("p", "Unit 3: Functions and Lists (Nov 2 to Dec 11). Defining functions, parameters, lists, the final project."),
    ("table", [["Date", "Event"], ["2026-10-28", "Unit 2 quiz"], ["2026-11-06", "Guessing game project due"],
               ["2026-12-11", "Final project due"]]),
    ("p", "Grading: projects 50%, quizzes 30%, classwork 20%."),
])
add(CS, "Python_Basics_Slides.pptx", "lecture", C1, [
    ("Unit 1: Getting Started with Python", "Your first programs"),
    ("print and variables", "print('Hello')\nname = 'Ada'\nVariables store values; = means assign."),
    ("Data types", "int, float, str, bool\nUse type(x) to check."),
    ("Input", "age = int(input('Age? '))\ninput() always returns a string."),
])
add(CS, "hello_world_starter.py", "worksheet", C1,
    "# Starter code: Hello, World and variables\n# 1. Run this file. 2. Change the name. 3. Add a line that prints your age next year.\n\n"
    "name = \"Ada\"\nprint(\"Hello, \" + name + \"!\")\n\n# TODO: ask the user for their age with input() and print it plus 1\n",
    note="Python code file, read as text")
add(CS, "Variables_and_Input_Worksheet.docx", "worksheet", C1, [
    ("h", "Worksheet: variables and input"),
    ("p", "1. What does this print?  x = 5; x = x + 2; print(x)"),
    ("p", "2. Why does int(input()) crash if the user types 'five'?"),
    ("p", "3. Write a program that asks for two numbers and prints their average."),
])
add(CS, "If_Statements_Notes.md", "lecture", C2,
    "# if / elif / else\n\n```python\nif score >= 90:\n    grade = 'A'\nelif score >= 80:\n    grade = 'B'\nelse:\n    grade = 'C or below'\n```\n\n"
    "Comparison operators: == != < > <= >=. Combine with and, or, not.\n", note="never names its unit")
add(CS, "Loops_Practice_Problems.pdf", "worksheet", C2,
    "LOOPS PRACTICE\n\n1. Use a for loop to print the numbers 1 to 10.\n2. Use a while loop to keep asking for a password until it is 'python'.\n"
    "3. Add up the even numbers from 2 to 100.\n4. Find the bug: for i in range(10): print(i) ... why does it stop at 9?")
add(CS, "guessing_game_project.py", ["worksheet", "other"], C2,
    "# Project: number guessing game (due 2026-11-06)\nimport random\n\nsecret = random.randint(1, 100)\nguesses = 0\n\n"
    "# TODO: loop until the player guesses the number\n# TODO: say 'too high' or 'too low' after each guess\n# TODO: print how many guesses it took\n",
    note="code file with a due date in a comment")
add(CS, "Unit2_Quiz_Loops.pdf", "quiz", C2,
    "UNIT 2 QUIZ: DECISIONS AND LOOPS   Date: 2026-10-28\n\n1. What does range(2, 8, 2) produce?\n"
    "2. Write an if/else that prints 'even' or 'odd'.\n3. How many times does while x < 5: x += 1 run if x starts at 0?\n"
    "4. Trace the loop: total = 0; for n in [3, 4, 5]: total += n")
add(CS, "debugging_trace_table_photo.jpg", "lecture", C2,
    ["TRACE TABLE  for i in range(4): total += i", "", "  i  | total", " ----+------", "  0  |   0", "  1  |   1",
     "  2  |   3", "  3  |   6", "", "final total = 6"], kind="photo", note="photo of a whiteboard: needs vision")
add(CS, "Functions_Slides.pptx", "lecture", C3, [
    ("Unit 3: Functions and Lists", "Reusable code"),
    ("Defining a function", "def area(w, h):\n    return w * h"),
    ("Parameters vs arguments", "Parameters are the names in the def; arguments are the values you pass."),
    ("Lists", "scores = [90, 85, 77]\nscores.append(100)\nlen(scores), scores[0], for s in scores"),
])
add(CS, "Lists_Cheat_Sheet.txt", ["lecture", "reading", "other"], C3,
    "PYTHON LISTS CHEAT SHEET\n\nmake: nums = [1, 2, 3]\nadd: nums.append(4)\nremove: nums.remove(2)\nlength: len(nums)\n"
    "first/last: nums[0], nums[-1]\nslice: nums[1:3]\nloop: for n in nums: print(n)\nsort: nums.sort()\n")
add(CS, "Final_Project_Rubric.docx", "rubric", [C3, None][0], [
    ("h", "Final project rubric (due 2026-12-11)"),
    ("table", [["Criterion", "Points"], ["Uses at least 3 functions", "10"], ["Uses a list", "10"],
               ["Has a loop and an if statement", "10"], ["Comments explain the code", "5"], ["Runs without errors", "15"]]),
])

# =================================================================== edge cases (drop into Algebra II)
EDGE = "edge_cases"
add(EDGE, "Graphing_Lines_Worksheet (1).docx", "worksheet", A1, "@copy:algebra2/Graphing_Lines_Worksheet.docx",
    kind="copy", note="exact duplicate of a file already filed: should say 'already in your library'")
add(EDGE, "Graphing_Lines_Worksheet_v2.docx", "worksheet", A1, [
    ("h", "Worksheet: Graphing Lines (version 2, with answer key)"),
    ("p", "1. Graph y = 2x - 3. Label the y-intercept.   Answer: crosses the y-axis at (0, -3)."),
    ("p", "2. Find the slope through (1, 4) and (5, 12).   Answer: 2."),
    ("p", "3. Parallel to y = -x + 6 through (0, 2).   Answer: y = -x + 2."),
], note="changed copy: filed as a separate file (not a duplicate)")
add(EDGE, "gradebook_export.xlsx", "other", None, "@xlsx",
    note="spreadsheet: not supported yet, should land in Needs review with the reason")
add(EDGE, "scan_blank_page.pdf", "other", None, [" "], kind="scan",
    note="blank scanned page: nothing to read, should go to Needs review")
add(EDGE, "IMG_4021.jpg", ["schedule", "other"], None,
    ["REMINDER", "", "Field trip permission slips", "due Friday 2026-12-04", "", "Science museum - bus leaves 8:15"], kind="photo",
    note="vague file name + photo of a sticky note: tests vision + date extraction")
add(EDGE, "Algebra2_Textbook_Ch3_Excerpt.pdf", "reading", A3, "@pages", kind="pages",
    note="8-page PDF: search hits should show page numbers")

TEXTBOOK_PAGES = [
    "Chapter 3: Quadratic Functions\n\nSection 3.1 Graphs of quadratics\nA quadratic function has the form f(x) = ax^2 + bx + c with a not equal to 0. Its graph is a parabola.",
    "Section 3.1 continued\nThe vertex is the turning point. When a > 0 the parabola opens upward and the vertex is a minimum.",
    "Section 3.2 Vertex form\nf(x) = a(x - h)^2 + k. The vertex is (h, k) and the axis of symmetry is the line x = h.",
    "Section 3.3 Factoring\nTo solve x^2 + bx + c = 0, find two numbers that multiply to c and add to b. Zero product property: if pq = 0 then p = 0 or q = 0.",
    "Section 3.4 Completing the square\nAdd (b/2)^2 to both sides to make a perfect square trinomial.",
    "Section 3.5 The quadratic formula\nx = (-b +/- sqrt(b^2 - 4ac)) / (2a) solves every quadratic equation.",
    "Section 3.6 The discriminant\nThe expression b^2 - 4ac tells how many real solutions there are before you solve.",
    "Section 3.7 Applications: projectile motion\nh(t) = -16t^2 + v0 t + h0 models the height of a thrown ball in feet after t seconds.",
]


def write_pages_pdf(path: Path, pages: list[str]) -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        for line in text.split("\n"):
            pdf.multi_cell(0, 7, line or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    """A minimal real .xlsx (inline strings) without extra dependencies."""
    def cell(r: int, c: int, v: str) -> str:
        ref = f"{chr(65 + c)}{r + 1}"
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    sheet = "".join(f'<row r="{r + 1}">' + "".join(cell(r, c, v) for c, v in enumerate(row)) + "</row>" for r, row in enumerate(rows))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Grades" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet}</sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def main() -> None:
    for folder in (ALG, CS, EDGE):
        d = OUT / folder
        d.mkdir(parents=True, exist_ok=True)
        for p in d.iterdir():
            p.unlink()
    for i, f in enumerate(FILES):
        path, kind, content = OUT / f["folder"] / f["name"], f["kind"], f["content"]
        if kind == "copy":
            path.write_bytes((OUT / content.split(":", 1)[1]).read_bytes())
        elif kind == "xlsx":
            write_xlsx(path, [["Student", "Unit 1 quiz", "Unit 2 test"], ["Student A", "88", "92"], ["Student B", "75", "81"]])
        elif kind == "pages":
            write_pages_pdf(path, TEXTBOOK_PAGES)
        elif kind == "docx":
            write_docx(path, content)
        elif kind == "pptx":
            write_pptx(path, content)
        elif kind == "pdf":
            write_pdf(path, content)
        elif kind in ("txt", "md", "py"):
            path.write_text(content, encoding="utf-8")
        elif kind == "photo":
            render_page(content, photo=True, seed=100 + i).save(path, quality=85)
        elif kind == "scan":
            render_page(content, photo=False, seed=100 + i).convert("L").save(path, "PDF", resolution=150)
        else:
            raise ValueError(f"{f['name']}: {kind}")
    expected = [{"folder": f["folder"], "file": f["name"], "doc_types": f["types"], "unit": f["unit"], "note": f["note"]}
                for f in FILES]
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    counts = {d: sum(f["folder"] == d for f in FILES) for d in (ALG, CS, EDGE)}
    print(f"wrote {len(FILES)} files to test_materials/: {counts}")


if __name__ == "__main__":
    main()
