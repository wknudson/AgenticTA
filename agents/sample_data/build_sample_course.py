"""Generates a realistic fake Biology Honors course for testing and demoing the filing system.

    npm run sample-course        (or: cd agents && uv run python sample_data/build_sample_course.py)

Writes:
  sample_data/biology_course/*            32 teacher files: DOCX, PPTX, PDF, TXT/MD, photos, a scanned PDF
  sample_data/biology_course_key.json     the right labels for each file (to grade the labeler)
  sample_data/search_eval.json            search questions + which files answer them (to grade search)

Everything is invented.  The term matches the scheduler's default (2026-08-24 to 2026-12-18).
Deterministic: re-running produces the same files.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import docx
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Pt

HERE = Path(__file__).resolve().parent
OUT = HERE / "biology_course"

U1, U2, U3, U4 = ("Unit 1: Chemistry of Life", "Unit 2: Cell Structure",
                  "Unit 3: Cell Energy", "Unit 4: Cell Division and Genetics")

# name -> (expected doc_type(s), expected unit or None, kind, content)
FILES: list[dict] = []


def add(name: str, types: str | list[str], unit: str | None, content, kind: str | None = None) -> None:
    FILES.append({"name": name, "types": [types] if isinstance(types, str) else types, "unit": unit,
                  "content": content, "kind": kind or Path(name).suffix.lower().lstrip(".")})


# ------------------------------------------------------------------ course-wide
add("Bio10_Syllabus_Fall2026.docx", "syllabus", None, [
    ("h", "Biology Honors (Period 1) Syllabus, Fall 2026"),
    ("p", "Teacher: Dr. Priya Sharma. Room: Lab B. Email through the school portal."),
    ("h", "What we study"),
    ("p", "Unit 1: Chemistry of Life (Aug 24 to Sep 18). Water, carbon, the four macromolecules, enzymes."),
    ("p", "Unit 2: Cell Structure (Sep 21 to Oct 16). Organelles, the cell membrane, diffusion, osmosis, active transport."),
    ("p", "Unit 3: Cell Energy (Oct 19 to Nov 13). Photosynthesis, cellular respiration, fermentation, ATP."),
    ("p", "Unit 4: Cell Division and Genetics (Nov 16 to Dec 11). Mitosis, meiosis, Mendel, Punnett squares."),
    ("h", "Key dates"),
    ("table", [["Date", "Event"], ["2026-09-17", "Unit 1 quiz"], ["2026-10-15", "Unit 2 test"],
               ["2026-11-12", "Unit 3 quiz"], ["2026-12-10", "Unit 4 test"], ["2026-12-16", "Final exam"]]),
    ("h", "Grading"),
    ("p", "Tests 40%, quizzes 20%, labs 25%, homework and worksheets 15%. Lab reports are graded with the lab report rubric."),
    ("p", "Late work: up to two days late for 80% credit. After that, talk to me. Every student may retake one quiz."),
    ("p", "AI tutor: use it to understand ideas, not to get answers. It will not answer assignment questions."),
])
add("Lab_Report_Rubric.docx", "rubric", None, [
    ("h", "Lab Report Rubric (all labs)"),
    ("table", [["Criterion", "4 Excellent", "2 Developing", "0 Missing"],
               ["Hypothesis", "Testable if/then statement tied to a variable", "Vague prediction", "None"],
               ["Data table", "Labeled columns, units, all trials", "Missing units or trials", "None"],
               ["Graph", "Correct type, axes labeled, title", "Wrong type or unlabeled", "None"],
               ["Conclusion", "Claim, evidence, reasoning; addresses error", "Claim only", "None"]]),
    ("p", "Total 16 points. Reports are due one week after the lab day unless the calendar says otherwise."),
])
add("Course_Calendar_Fall2026.txt", "schedule", None,
    "BIOLOGY HONORS COURSE CALENDAR, FALL 2026\n\n"
    "Aug 24  First day, lab safety contract\n2026-09-02  Toothpickase enzyme lab\n"
    "2026-09-17  Unit 1 quiz (macromolecules and enzymes)\n2026-09-29  Osmosis egg lab day 1\n"
    "2026-10-01  Osmosis egg lab day 2\n2026-10-15  Unit 2 test\n2026-10-28  Leaf disk photosynthesis lab\n"
    "2026-11-12  Unit 3 quiz (cell energy)\n2026-11-25 to 2026-11-27  Thanksgiving break, no school\n"
    "2026-12-02  Onion root tip mitosis lab\n2026-12-10  Unit 4 test (genetics)\n2026-12-16  Final exam\n")
add("Lab_Safety_Contract.pdf", ["other", "lab"], None,
    "LAB SAFETY CONTRACT\n\nRead each rule, then sign and return by the end of the first week.\n\n"
    "1. Wear goggles whenever chemicals, heat, or glassware are out.\n2. Tie back long hair and roll up loose sleeves.\n"
    "3. Never eat or drink in the lab, even after cleanup.\n4. Report every spill, cut, or broken glass to the teacher at once.\n"
    "5. Know where the eyewash station, fire blanket, and extinguisher are.\n6. Wash your hands before leaving.\n\n"
    "Student signature: ______________    Parent signature: ______________")
add("Parent_Welcome_Letter.docx", "other", None, [
    ("p", "Dear families,"),
    ("p", "Welcome to Biology Honors! This year your student will look at life from molecules to cells to inheritance. "
          "We do a lot of hands-on labs, so please make sure the safety contract comes back signed."),
    ("p", "You can follow assignments and grades in the class portal. Please reach out any time with questions."),
    ("p", "Warmly, Dr. Sharma"),
])
add("Final_Exam_Review_Guide.docx", ["worksheet", "other"], None, [
    ("h", "Final Exam Review Guide"),
    ("p", "The final on 2026-12-16 covers all four units. Use this guide to find gaps."),
    ("p", "Unit 1: Name the monomer of each macromolecule. Why does an enzyme stop working when it is heated?"),
    ("p", "Unit 2: Compare passive and active transport. What would happen to a plant cell in salt water?"),
    ("p", "Unit 3: Write the equations for photosynthesis and cellular respiration. Where does each happen?"),
    ("p", "Unit 4: How is meiosis different from mitosis? Solve a monohybrid cross for a heterozygous parent."),
])

# ------------------------------------------------------------------ unit 1
add("Unit1_Water_and_Carbon_Slides.pptx", "lecture", U1, [
    ("Unit 1: Chemistry of Life", "Why chemistry matters for living things"),
    ("Water is polar", "Oxygen pulls electrons harder than hydrogen, so water has partial charges.\nHydrogen bonds hold water molecules together."),
    ("Properties of water", "Cohesion and surface tension\nHigh specific heat keeps temperatures steady\nIce floats because it is less dense"),
    ("Carbon is the backbone", "Carbon makes four bonds, forming chains and rings.\nThis is why living things are built on carbon."),
])
add("U1 macromolecules notes.md", "lecture", U1,
    "# Unit 1 notes: the four macromolecules\n\n"
    "| Macromolecule | Monomer | Job |\n|---|---|---|\n| Carbohydrates | monosaccharides (glucose) | quick energy, structure (cellulose) |\n"
    "| Lipids | fatty acids and glycerol | long-term energy, cell membranes |\n| Proteins | amino acids | enzymes, structure, transport |\n"
    "| Nucleic acids | nucleotides | store and pass on genetic information (DNA, RNA) |\n\n"
    "Dehydration synthesis joins monomers by removing water. Hydrolysis breaks polymers apart by adding water.\n")
add("Macromolecules_Worksheet.docx", "worksheet", U1, [
    ("h", "Unit 1 Worksheet: Macromolecules"),
    ("p", "1. Sort these foods by the main macromolecule they contain: bread, olive oil, chicken, rice, butter."),
    ("p", "2. What is the monomer of a protein? How many different kinds are there?"),
    ("p", "3. Explain the difference between dehydration synthesis and hydrolysis."),
    ("p", "4. Why are phospholipids a good material for a cell membrane?"),
])
add("Enzyme_Lab_Toothpickase.pdf", "lab", U1,
    "LAB: TOOTHPICKASE (ENZYME MODEL)   Lab date: 2026-09-02\n\n"
    "Your hand is the enzyme 'toothpickase' and toothpicks are the substrate. Break as many toothpicks as you can in 10 seconds.\n\n"
    "Trials: normal conditions; more substrate; a 'denatured' enzyme (non-dominant hand taped); competitive inhibitor (paper clips mixed in).\n\n"
    "Questions: How does substrate concentration change the reaction rate? What does denaturing do to an enzyme's active site? "
    "Write a hypothesis before you start and graph rate vs. substrate amount.")
add("Unit1_Quiz_Macromolecules.pdf", "quiz", U1,
    "UNIT 1 QUIZ: MACROMOLECULES AND ENZYMES   Date: 2026-09-17\n\n"
    "1. Which macromolecule stores genetic information?  a) lipid  b) protein  c) nucleic acid  d) carbohydrate\n"
    "2. Enzymes speed up reactions by lowering the ________ energy.\n"
    "3. True or false: a denatured enzyme can still bind its substrate normally.\n"
    "4. Short answer: why does water have a high specific heat, and why does that matter for organisms?")
add("Reading_Why_Water_Is_Weird.txt", "reading", U1,
    "Why Water Is Weird (short reading)\n\nMost substances get denser when they freeze, but water does the opposite. "
    "As water cools below 4 degrees Celsius, hydrogen bonds lock molecules into an open crystal, so ice floats. "
    "That floating layer insulates lakes in winter, which lets fish survive under the ice. Water's high specific heat also "
    "means coastal cities have milder temperatures than inland ones.\n\nDiscussion: what would happen to lake life if ice sank?")

# ------------------------------------------------------------------ unit 2
add("Cell_Organelles_Slides.pptx", "lecture", U2, [
    ("Unit 2: Cell Structure", "A tour of the cell"),
    ("Prokaryotes vs eukaryotes", "Prokaryotes: no nucleus, smaller (bacteria)\nEukaryotes: nucleus and membrane-bound organelles"),
    ("The nucleus and ribosomes", "Nucleus stores DNA and controls the cell.\nRibosomes build proteins."),
    ("Mitochondria and chloroplasts", "Mitochondria release energy from food (ATP).\nChloroplasts capture light energy in plants."),
    ("Plant vs animal cells", "Plants have a cell wall, chloroplasts and a large central vacuole."),
])
add("cell_membrane_transport_notes.txt", "lecture", U2,
    "Unit 2 notes: the cell membrane and transport\n\nThe membrane is a phospholipid bilayer with proteins floating in it (fluid mosaic model). "
    "It is selectively permeable.\n\nPassive transport needs no energy: diffusion, osmosis (water moving across a membrane), facilitated diffusion through channel proteins.\n"
    "Active transport uses ATP to move things against the concentration gradient, like the sodium-potassium pump.\n"
    "Hypotonic solution: cell gains water and swells. Hypertonic: cell loses water and shrinks. Isotonic: no net change.")
add("Organelle_Analogy_Worksheet.docx", "worksheet", U2, [
    ("h", "Worksheet: The Cell as a City"),
    ("p", "Match each organelle to a part of a city and explain why: nucleus, mitochondria, cell membrane, ribosome, Golgi apparatus, lysosome."),
    ("p", "City parts: city hall, power plant, border checkpoint, factory, post office, recycling center."),
    ("p", "Bonus: what part of the city would a chloroplast be, and why don't animal-cell cities have one?"),
])
add("Osmosis_Egg_Lab.pdf", "lab", U2,
    "LAB: THE NAKED EGG (OSMOSIS)   Days: 2026-09-29 and 2026-10-01\n\n"
    "Day 1: Soak an egg in vinegar to dissolve the shell, leaving only the membrane. Measure its mass.\n"
    "Day 2: Move eggs into distilled water, corn syrup, or salt water. Predict whether each egg will gain or lose mass, then measure again.\n\n"
    "Analysis: Which solution was hypotonic, hypertonic, or isotonic to the egg? Calculate percent change in mass.")
add("Unit 2 Test - Cell Structure.pdf", "test", U2,
    "UNIT 2 TEST: CELL STRUCTURE AND TRANSPORT   Date: 2026-10-15\n\n"
    "Part A (multiple choice)\n1. Which organelle builds proteins?\n2. Which structure is found in plant cells but not animal cells?\n"
    "Part B (short answer)\n3. Explain why a red blood cell bursts in distilled water.\n"
    "4. Compare facilitated diffusion and active transport.\nPart C (diagram)\n5. Label the phospholipid bilayer.")
add("organelle_matching_scan.png", "worksheet", U2,
    ["Name: ____________   Period: 1", "ORGANELLE MATCHING (Unit 2)", "",
     "1. Nucleus ........ A. makes ATP", "2. Mitochondria .... B. controls the cell, holds DNA",
     "3. Ribosome ....... C. packages and ships proteins", "4. Golgi body ..... D. builds proteins",
     "5. Lysosome ....... E. breaks down waste", "", "Bonus: draw a plant cell and label the cell wall."], kind="image")
add("Reading_Endosymbiosis.txt", "reading", U2,
    "Reading: Where did mitochondria come from?\n\nLynn Margulis argued that mitochondria and chloroplasts were once free-living bacteria "
    "that were swallowed by a larger cell but not digested. Evidence: they have their own circular DNA, their own ribosomes, "
    "and two membranes, and they divide like bacteria. This idea is called endosymbiotic theory.")

# ------------------------------------------------------------------ unit 3
add("Photosynthesis_Slides.pptx", "lecture", U3, [
    ("Unit 3: Cell Energy", "Photosynthesis"),
    ("The big equation", "6CO2 + 6H2O + light energy -> C6H12O6 + 6O2"),
    ("Light-dependent reactions", "Happen in the thylakoid membranes.\nChlorophyll absorbs light; water is split; oxygen is released; ATP and NADPH are made."),
    ("The Calvin cycle", "Happens in the stroma.\nUses ATP and NADPH to fix carbon dioxide into glucose."),
    ("Limiting factors", "Light intensity, carbon dioxide, and temperature change the rate."),
])
add("Cellular_Respiration_Notes.docx", "lecture", U3, [
    ("h", "Unit 3 Notes: Cellular Respiration"),
    ("p", "C6H12O6 + 6O2 -> 6CO2 + 6H2O + ATP. Respiration is how cells release energy stored in glucose."),
    ("p", "Glycolysis (cytoplasm): glucose is split into two pyruvate, making 2 ATP."),
    ("p", "Krebs cycle (mitochondrial matrix): releases CO2 and loads electron carriers."),
    ("p", "Electron transport chain (inner mitochondrial membrane): makes most of the ATP, about 34, and needs oxygen."),
    ("p", "Without oxygen, cells use fermentation: lactic acid in muscles, alcohol and CO2 in yeast."),
])
add("Photosynthesis_vs_Respiration_Worksheet.docx", "worksheet", U3, [
    ("h", "Worksheet: Photosynthesis vs Cellular Respiration"),
    ("table", [["", "Photosynthesis", "Cellular respiration"], ["Organelle", "", ""], ["Reactants", "", ""],
               ["Products", "", ""], ["Energy change", "", ""]]),
    ("p", "Explain how the two processes form a cycle between plants and animals."),
])
add("Leaf_Disk_Lab.pdf", "lab", U3,
    "LAB: FLOATING LEAF DISKS   Lab date: 2026-10-28\n\n"
    "Punch disks from spinach leaves and remove the air with a syringe so they sink in baking soda solution. "
    "Under a lamp, oxygen from photosynthesis collects in the disks and they float.\n\n"
    "Variable: distance from the light. Record how many disks float each minute for 15 minutes and find the time for half to float (ET50).")
add("Unit3_Quiz_Cell_Energy.pdf", "quiz", U3,
    "UNIT 3 QUIZ: CELL ENERGY   Date: 2026-11-12\n\n"
    "1. Where do the light-dependent reactions happen?\n2. What gas is a product of cellular respiration?\n"
    "3. Which stage of respiration makes the most ATP?\n4. Why do your muscles burn during a sprint?")
add("whiteboard_atp_cycle.jpg", "lecture", U3,
    ["ATP / ADP CYCLE  (Unit 3)", "", "ATP = adenosine + 3 phosphates", "energy released when the 3rd phosphate breaks off",
     "ATP  ->  ADP + P  + ENERGY  (used for work)", "ADP + P + energy from food  ->  ATP", "",
     "rechargeable battery analogy!"], kind="photo")
add("Reading_Fermentation_Bread.txt", "reading", U3,
    "Reading: The science of bread\n\nWhen bakers mix yeast into dough, the yeast break down sugars without much oxygen. "
    "This anaerobic process, alcoholic fermentation, produces carbon dioxide gas and a little ethanol. The CO2 bubbles get "
    "trapped in the stretchy gluten, which is why dough rises. The ethanol bakes off in the oven.")

# ------------------------------------------------------------------ unit 4
add("Mitosis_Meiosis_Slides.pptx", "lecture", U4, [
    ("Unit 4: Cell Division and Genetics", "How cells divide"),
    ("The cell cycle", "Interphase (G1, S, G2) then mitosis and cytokinesis.\nDNA is copied during the S phase."),
    ("Phases of mitosis", "Prophase, metaphase, anaphase, telophase.\nResult: two identical diploid cells, for growth and repair."),
    ("Meiosis", "Two divisions make four haploid gametes.\nCrossing over and independent assortment create genetic variation."),
])
add("Mendel_Genetics_Notes.md", "lecture", U4,
    "# Unit 4 notes: Mendel and inheritance\n\n"
    "Gregor Mendel bred pea plants and found that traits come from pairs of factors we now call alleles.\n\n"
    "- Dominant alleles hide recessive ones (capital vs lowercase letters).\n- Genotype is the allele pair (Tt); phenotype is the trait you see (tall).\n"
    "- Homozygous: TT or tt. Heterozygous: Tt.\n- Law of segregation: allele pairs separate when gametes form.\n")
add("Punnett_Square_Practice.docx", "worksheet", U4, [
    ("h", "Punnett Square Practice"),
    ("p", "1. In pea plants, purple flowers (P) are dominant to white (p). Cross Pp x pp. What fraction of offspring are white?"),
    ("p", "2. Two heterozygous tall plants are crossed. Give the genotype and phenotype ratios."),
    ("p", "3. A brown-eyed parent and a blue-eyed parent have a blue-eyed child. What is the brown-eyed parent's genotype?"),
])
add("Onion_Root_Tip_Lab.pdf", "lab", U4,
    "LAB: ONION ROOT TIP MITOSIS   Lab date: 2026-12-02\n\n"
    "Look at a prepared slide of an onion root tip under high power. Count 50 cells and record which phase of the cell cycle each is in.\n\n"
    "Use your counts to estimate how long each phase lasts if the full cycle takes 24 hours. Which phase is the longest, and why?")
add("Unit4_Test_Genetics_scanned.pdf", "test", U4,
    ["UNIT 4 TEST: CELL DIVISION AND GENETICS", "Date: 2026-12-10        Name: ____________", "",
     "1. List the phases of mitosis in order.", "2. How many chromosomes are in a human gamete?",
     "3. Explain how crossing over increases variation.", "4. Cross Tt x Tt. Give the phenotype ratio.",
     "5. Define genotype and phenotype."], kind="scan")
add("Reading_CRISPR_News.txt", "reading", U4,
    "Reading: Editing genes with CRISPR\n\nCRISPR-Cas9 is a tool, borrowed from bacteria, that cuts DNA at a chosen spot. "
    "Scientists can then remove or replace a gene. In 2023 the first CRISPR therapy was approved to treat sickle cell disease. "
    "Questions for discussion: should we edit genes in embryos? Who decides which traits are 'fixable'?")


# ------------------------------------------------------------------ writers
def write_docx(path: Path, blocks) -> None:
    d = docx.Document()
    for kind, val in blocks:
        if kind == "h":
            d.add_heading(val, level=2)
        elif kind == "p":
            d.add_paragraph(val)
        elif kind == "table":
            t = d.add_table(rows=len(val), cols=len(val[0]))
            for r, row in enumerate(val):
                for c, cell in enumerate(row):
                    t.cell(r, c).text = cell
    d.core_properties.author = "P. Sharma"
    d.save(path)


def write_pptx(path: Path, slides) -> None:
    prs = Presentation()
    for i, (title, body) in enumerate(slides):
        s = prs.slides.add_slide(prs.slide_layouts[0 if i == 0 else 1])
        s.shapes.title.text = title
        ph = s.placeholders[1]
        ph.text = body
        for p in ph.text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(24)
    prs.save(path)


def write_pdf(path: Path, text: str) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.split("\n"):
        pdf.multi_cell(0, 6, line or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def render_page(lines: list[str], *, photo: bool, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    w, h = (1400, 1000) if photo else (1275, 1650)
    bg = (236, 238, 232) if photo else (250, 248, 240)
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=44 if photo else 34)
    y = 90
    for line in lines:
        draw.text((90 + rnd.randint(-6, 6), y), line, fill=(30, 40, 120) if photo else (25, 25, 25), font=font)
        y += 70 if photo else 58
    img = img.rotate(rnd.uniform(-2.0, 2.0), expand=False, fillcolor=bg)
    noise = Image.effect_noise((w, h), 18).convert("RGB")
    img = Image.blend(img, noise, 0.06).filter(ImageFilter.GaussianBlur(0.6))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        p.unlink()
    for i, f in enumerate(FILES):
        path, kind, content = OUT / f["name"], f["kind"], f["content"]
        if kind == "docx":
            write_docx(path, content)
        elif kind == "pptx":
            write_pptx(path, content)
        elif kind == "pdf":
            write_pdf(path, content)
        elif kind in ("txt", "md"):
            path.write_text(content, encoding="utf-8")
        elif kind == "image":  # grayscale with few tones keeps the "scan" small enough to commit
            render_page(content, photo=False, seed=i).convert("L").point(lambda v: (v // 32) * 32).save(path, optimize=True)
        elif kind == "photo":
            render_page(content, photo=True, seed=i).save(path, quality=85)
        elif kind == "scan":  # image-only PDF: no text layer, so the pipeline must use vision
            render_page(content, photo=False, seed=i).save(path, "PDF", resolution=150)
        else:
            raise ValueError(kind)

    key = [{"file": f["name"], "doc_types": f["types"], "unit": f["unit"], "needs_vision": f["kind"] in ("image", "photo", "scan")}
           for f in FILES]
    (HERE / "biology_course_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"wrote {len(FILES)} files to {OUT.relative_to(HERE.parent)} and the answer key")


if __name__ == "__main__":
    main()
