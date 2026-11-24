"""The no-AI unit package generator: deterministic, built for real course text.

Used when the games agent has no model keys, or when the teacher asks for `offline: true`.
Same input (the unit's filed Library text) always gives the same package.

How key terms are found, per sentence (after stripping bullets, numbering and **bold**):

    glossary line   "Hypotonic solution: cell gains water and swells."   (also " - ", " – ", " — ")
    table row       | Lipids | fatty acids and glycerol | long-term energy |   (header names the columns)
    "X is/are ..."  "Respiration is how cells release energy stored in glucose."
    "X <verb> ..."  "Ribosomes build proteins."  (a short noun phrase + a defining verb)
    parentheses     "..., osmosis (water moving across a membrane), ..."
    slide heading   "The Calvin cycle" followed by "Happens in the stroma."

Quizzes, tests, rubrics, syllabi and schedules are skipped (they're questions, not explanations);
worksheets and labs only count when the lecture notes and readings run out.

"Explain" questions come from sentences with a reason in them ("..., so water has partial
charges", "Ice floats because ...", "This is why ...", "X uses Y to Z"), then from contrast pairs
in the unit's terms (hypotonic / hypertonic, prokaryotes / eukaryotes), then "X: explain what it
does and why it matters". The rubric is always the source sentence(s).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

MIN_CARDS = 4          # fewer than this and the games aren't worth playing: 409
MAX_GAME_ITEMS = 8     # matching pairs / fill-in sentences per package

SKIP_TYPES = {"quiz", "test", "rubric", "syllabus", "schedule"}
TYPE_RANK = {"worksheet": 1, "lab": 2}     # lecture, reading, other, unlabeled: 0
PATTERN_RANK = {"glossary": 0, "table": 0, "copula": 0, "verb": 0, "paren": 1, "heading": 2}


class NotEnoughMaterial(ValueError):
    """The unit's text doesn't hold enough definitions for a package (-> HTTP 409)."""


@dataclass
class Source:
    file_id: int
    title: str
    doc_type: str | None
    text: str


@dataclass
class Fact:
    term: str                 # as written, without a leading article ("Calvin cycle")
    definition: str           # display form ("Happens in the stroma.")
    sentence: str             # the source sentence(s) it came from (the rubric for explain questions)
    kind: str                 # glossary | table | copula | verb | paren | heading
    source: str               # file title
    file_idx: int
    rank: int
    pos: int
    blank: str | None = None  # source sentence with the term blanked ("____ build proteins.")

    @property
    def key(self) -> str:
        return norm_term(self.term)


@dataclass
class Reason:
    question: str
    answer: str
    sentence: str
    source: str
    rank: int
    pos: int
    terms: tuple[str, ...] = ()


# ---------------------------------------------------------------- word lists
_SUBJECT_STOP = set("""this that these those it its they them their there here we you your our my i he she his her
each every most many some all both any one two three four five six seven eight nine ten several few other another
such which what who whom whose why how when where if then also only just without with for from in on at by to as
after before during while because so but or nor not no yes students student teacher teachers class everyone someone
people today tomorrow yesterday next last first second third finally""".split())
_FUNCTION = set("""because so it its they them that which who when if than then this these those there here we you
also not no only most very can will may might should would could do does did has have had be been being is are was
were their our your my but or to from with by at on as into about like such each every all some many much more less
get gets got for""".split())
_LABELS = set("""analysis answer answers bonus conclusion date day days directions discussion due evidence example
examples goal goals homework hypothesis instructions key lab labs materials name note notes objective objectives part
period procedure purpose question questions quiz reading result results review step steps summary test tip trials
unit vocabulary warning worksheet agenda today tonight reminder remember hint source sources chapter section page
figure fig table class practice exam warm-up warmup exit ticket handout slide slides lesson topic topics overview
introduction intro agenda""".split()) | {"true or false", "city parts", "word bank", "key terms", "lab date"}
_IMPERATIVE = set("""explain sort match compare describe label write predict measure calculate cross give list name
define draw soak move break read use find identify complete fill circle choose select make build design graph record
observe discuss answer show look think try add mix place put pour remove take watch fold cut glue color colour
underline highlight review study research summarize state outline justify evaluate analyze analyse discuss
factor solve simplify rewrite expand convert plot sketch determine prove verify check estimate round apply
substitute multiply divide subtract combine reduce""".split())  # math worksheet instructions ("Factor completely: 1) ...")
_VERB_BASES = """store build make control release capture use need hold produce contain break join move absorb protect
transport convert form help keep provide digest package regulate allow let cause speed lower raise pull hide split turn
create carry copy fix bind attach link connect separate divide pump trap insulate sort ship modify destroy recycle clean
filter support shape detect send receive respond act work serve consist include determine code encode direct replicate
synthesize catalyze transfer generate supply power fuel remove add take give lose gain absorb reflect emit""".split()
_CONT_BASES = _VERB_BASES + ["happen", "occur", "begin", "end", "start", "follow", "take"]


def _forms(base: str) -> set[str]:
    if base.endswith("y") and base[-2] not in "aeiou":
        return {base, base[:-1] + "ies"}
    if base.endswith(("s", "sh", "ch", "x", "z")):
        return {base, base + "es"}
    return {base, base + "s"}


_BASE_VERBS = set(_VERB_BASES)
_SINGULAR_VERBS = {f for b in _VERB_BASES for f in _forms(b)} - _BASE_VERBS
_CONT_VERBS = {f for b in _CONT_BASES for f in _forms(b)}
_COPULAS = {"is", "are", "was", "were", "means", "refers"}
_IRREGULAR_PP = set("""split made built found known given taken done seen held kept broken copied called used shown
grown thrown drawn born worn torn bound spun shed set put cut hit read led fed bred sent spent lost left meant brought
bought caught taught thought sold told won run begun become come""".split())
_NAMED_LAST = {"cycle", "theory", "law", "model", "principle", "effect"}   # Krebs cycle -> "Krebs" is enough
_COMMON_SUFFIXES = ("tion", "sion", "ment", "ness", "ing", "ity", "ism", "ance", "ence", "ous", "ive", "ers", "ies")

# ---------------------------------------------------------------- patterns
_WORD = r"[A-Za-z][A-Za-z0-9'\-]*"
_TERM = rf"{_WORD}(?: {_WORD}){{0,3}}"
_ART = r"(?:(?:The|the|A|a|An|an) )?"
_WORD_RE = re.compile(rf"^{_WORD}$")

# The subject is lazy, so the FIRST "is/are" splits it ("Genotype is the allele pair").
COPULA = re.compile(rf"^{_ART}(?P<term>{_WORD}(?: {_WORD}){{0,3}}?) (?P<verb>is defined as|is known as|refers to|is|are|means) "
                    rf"(?P<def>.+)$")
GLOSSARY = re.compile(rf"^{_ART}(?P<term>{_TERM})(?: \((?P<paren>[^()]{{1,40}})\))?\s*(?::|\s[-–—]\s)\s*(?P<def>\S.*)$")
PAREN = re.compile(rf"(?:^|[,:;]\s*)(?P<term>{_WORD}(?: {_WORD}){{0,2}}) \((?P<def>[^()]{{6,80}})\)")

BECAUSE = re.compile(r"^(?P<effect>[A-Z][^,;?]*?),? because (?P<cause>[^?]+)$")
SO = re.compile(r"^(?P<cause>[A-Z][^?]*?),\s+(?:and so|so|which is why|that is why|that's why|therefore|as a result,?)\s+"
                r"(?P<effect>[^?]+)$")
THIS_IS_WHY = re.compile(r"^(?:This|That) is why (?P<effect>[^?]+)$")
WHICH_LETS = re.compile(r"^(?P<cause>[A-Z][^?]*?),\s+which (?P<verb>means|lets|allows|helps) (?P<effect>[^?]+)$")
USES_TO = re.compile(rf"^{_ART}(?P<subj>{_TERM}) (?P<verb>uses|use|needs|need|requires|require) (?P<obj>[^,]+?) "
                     rf"to (?P<purpose>[a-z][^?]+)$")

_BULLET = re.compile(r"^\s*(?:#{1,6}\s+|[-*•+▪◦]\s+|\(?\d{1,2}[.)]\s+|\(?[a-hA-H][.)]\s+)")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


# ---------------------------------------------------------------- small helpers
def norm_term(term: str) -> str:
    t = re.sub(r"^(the|a|an) ", "", re.sub(r"\s+", " ", term.lower().strip()))
    words = t.split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith(("ss", "us", "is")):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def stable_hash(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


def _clean_line(line: str) -> tuple[str, bool]:
    raw = line.strip()
    bulleted = bool(_BULLET.match(raw))
    text = _BULLET.sub("", raw)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"(?<!\w)\*(\S[^*]*?)\*(?!\w)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(), bulleted


_CODE_START = re.compile(r"^(for|if|elif|else|while|def|return|print|import|from|class|lambda|with|try)\b")


def _looks_like_code_or_math(text: str) -> bool:
    """Case matters in math variables and code (Python's len, for, print): leave those as written."""
    first = text.split(maxsplit=1)[0] if text.split() else ""
    return bool(re.match(r"^[a-z]\s*[=(<>^+\-*/]", text)           # y = ..., f(x)
                or re.search(r"[\[\](){}=<>^*/_.]|\d", first)      # len(nums), nums[1:3], x_1
                or (_CODE_START.match(text) and re.search(r"[:()\[\]=]", text)))  # for n in nums: ...


def _sentence(text: str) -> str:
    text = text.strip().rstrip(" ;,")
    if not text:
        return text
    if not _looks_like_code_or_math(text):  # "y = ax^2", "len(nums)": capitals would change the meaning
        text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _proper(word: str, unit_text: str) -> bool:
    """A name: written with a capital in the middle of a line somewhere ("Gregor Mendel")."""
    for m in re.finditer(rf"(\S+)[ \t]+{re.escape(word)}\b", unit_text):
        if not re.search(r"[.!?:|#\-*•]$|^\d+[.)]$", m.group(1)):
            return True
    return False


def _lc_first(text: str, unit_text: str = "", term: bool = False) -> str:
    """'Ice floats' -> 'ice floats' mid-sentence, but keep 'ATP', 'Mendel' and 'Krebs cycle'."""
    first = text.split(" ", 1)[0]
    if len(first) > 1 and (first.isupper() or any(c.isupper() for c in first[1:])):
        return text
    if unit_text and first[:1].isupper() and _proper(first, unit_text):
        return text
    words = text.split()
    if (term and len(words) == 2 and words[1].lower() in _NAMED_LAST
            and not re.search(rf"\b{re.escape(first.lower())}\b", unit_text)):
        return text
    return text[:1].lower() + text[1:]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text)


def _ok_term(term: str) -> bool:
    words = term.split()
    lw = [w.lower() for w in words]
    if not words or len(words) > 4:
        return False
    if lw[0] in _SUBJECT_STOP or lw[0] in _IMPERATIVE or lw[0] in _LABELS or " ".join(lw) in _LABELS:
        return False
    if any(w in _FUNCTION or w in _COPULAS for w in lw):
        return False
    if any(w.isdigit() for w in lw) or len(term) < 3:
        return False
    if term.isupper() and len(term.replace(" ", "")) > 5:   # SHOUTED headings ("UNIT 3 QUIZ")
        return False
    return True


def _passive(definition: str) -> bool:
    first = definition.split(" ", 1)[0].lower()
    second = (definition.split(" ") + ["", ""])[1].lower()
    if first in _IRREGULAR_PP or (len(first) > 4 and first.endswith("ed")):
        return True
    return first.endswith("ly") and (second in _IRREGULAR_PP or second.endswith("ed"))


def _verb_split(clause: str) -> tuple[str, str] | None:
    """'Nucleus stores DNA and controls the cell' -> ('Nucleus', 'stores DNA and controls the cell').

    The subject is the shortest 1-4 word noun phrase followed by a defining verb that agrees
    with it, so 'Electron transport chain' isn't read as 'Electron' + 'transport', and
    'Sodium-potassium pump moves ...' isn't 'Sodium-potassium' + 'pump'."""
    tokens = clause.split(" ")
    if tokens and tokens[0] in ("The", "the", "A", "a", "An", "an"):
        tokens = tokens[1:]
    for k in range(1, min(4, len(tokens) - 1) + 1):
        verb = tokens[k]
        if verb not in _BASE_VERBS and verb not in _SINGULAR_VERBS:
            continue
        term = " ".join(tokens[:k])
        if not all(_WORD_RE.match(t) for t in tokens[:k]) or not _ok_term(term):
            continue
        plural = _is_plural(term) or " and " in term
        either = term.split()[-1].lower().endswith(("ia", "data"))
        if not either and plural == (verb in _SINGULAR_VERBS):
            continue
        definition = " ".join(tokens[k:])
        if len(definition.split()) >= 2:
            return term, definition
    return None


def _mask(term: str, text: str) -> str:
    return re.sub(rf"\b{re.escape(term)}\b", "it", text, flags=re.IGNORECASE)


def _is_plural(term: str) -> bool:
    last = term.split()[-1].lower()
    return (last.endswith("s") and not last.endswith(("ss", "us", "is"))) or last.endswith(("ia", "ae", "i"))


def alternates(answer: str, unit_text: str = "") -> list[str]:
    """Accepted variants for a fill-in answer: irregular singular/plural (mitochondria ->
    mitochondrion, nucleus -> nuclei), a plural without its s, no hyphen, "hypotonic" for
    "hypotonic solution", "Krebs" for "Krebs cycle". Lower case; the player compares
    case-insensitively and forgives small typos, so regular plurals need no entry."""
    original = answer.strip()
    a = original.lower()
    words = a.split()
    out: set[str] = set()
    last = words[-1]
    variants = set()
    if last.endswith("ria"):
        variants.add(last[:-1] + "on")              # mitochondria -> mitochondrion
    elif last.endswith("rion"):
        variants.add(last[:-2] + "a")
    if last.endswith("us") and not last.endswith("ous") and len(last) > 4:
        variants.add(last[:-2] + "i")               # nucleus -> nuclei
    elif last.endswith("i") and len(last) > 4:
        variants.add(last[:-1] + "us")
    if last.endswith("ies"):
        variants.add(last[:-3] + "y")
    elif last.endswith("es") and last[:-2].endswith(("ss", "sh", "ch", "x", "z")):
        variants.add(last[:-2])
    elif last.endswith("s") and not last.endswith(("ss", "us", "is")) and len(last) > 3:
        variants.add(last[:-1])
    for v in variants:
        out.add(" ".join([*words[:-1], v]))
    if "-" in a:
        out.add(a.replace("-", " "))
    if len(words) == 2 and words[1] in ("solution", "solutions"):
        out.add(words[0])                           # hypotonic solution -> hypotonic
    if (len(words) == 2 and words[1] in _NAMED_LAST and original[:1].isupper()
            and not re.search(rf"\b{re.escape(words[0])}\b", unit_text)):
        out.add(words[0])                           # Krebs cycle -> krebs (a name: never written in lower case)
    out.discard(a)
    return sorted(out)


# ---------------------------------------------------------------- extraction
class _Extractor:
    def __init__(self, sources: list[Source]):
        self.sources = [s for s in sources if (s.doc_type or "") not in SKIP_TYPES and s.text.strip()]
        self.text = "\n".join(s.text for s in sources)   # all of it (tests too), for casing checks
        self.facts: list[Fact] = []
        self.reasons: list[Reason] = []
        self.pos = 0

    def run(self) -> "_Extractor":
        for idx, src in enumerate(self.sources):
            self._file(idx, src)
        return self

    def _add(self, fact: Fact) -> None:
        fact.definition = _sentence(_mask(fact.term, fact.definition))
        if not re.search(r"[A-Za-z]", fact.definition) or "?" in fact.definition or "___" in fact.definition:
            return
        if len(fact.definition) > 240:
            return
        if len(_words(fact.definition)) < 2:
            return  # a cut-off fragment ("If.") makes a nonsense card
        if len(re.findall(r"(?:^|\s)\(?\d{1,2}[.)]\s", fact.definition)) >= 2:
            return  # a numbered exercise list, not a definition
        self.pos += 1
        fact.pos = self.pos
        self.facts.append(fact)

    def _file(self, idx: int, src: Source) -> None:
        type_rank = TYPE_RANK.get(src.doc_type or "", 0)
        lines = [_clean_line(line) for line in src.text.splitlines()]
        lines = [(t, b) for t, b in lines if t]
        table: list[list[str]] = []
        found_on_line: list[bool] = []
        prev_sentence = ""
        for i, (line, bulleted) in enumerate(lines):
            if line.count("|") >= 1 and len([c for c in line.strip("|").split("|")]) >= 2:
                table.append([c.strip() for c in line.strip().strip("|").split("|")])
                found_on_line.append(True)
                continue
            if table:
                self._table(idx, src, table, type_rank)
                table = []
            found = False
            sentences = _SENT_SPLIT.split(line)
            for si, sent in enumerate(sentences):
                sent = sent.strip()
                if not sent or "?" in sent or "___" in sent or len(sent) > 400:
                    prev_sentence = sent
                    continue
                starts_ok = sent[0].isupper() or bulleted or si > 0 or sent[0] in "\"'("
                if starts_ok:
                    self._reasons(idx, src, sent, prev_sentence, type_rank)
                for ci, clause in enumerate(re.split(r";\s+", sent)):
                    if starts_ok or ci > 0:
                        found |= self._clause(idx, src, clause.strip(), type_rank)
                    elif si == 0 and len(sentences) == 1:
                        # A lowercase line can't be trusted as a sentence (it may be a wrapped
                        # continuation), but a whole "term: definition" line is a glossary entry
                        # ("axis of symmetry: x = h" in math notes).
                        found |= self._clause(idx, src, clause.strip(), type_rank, glossary_only=True)
                if type_rank < 2:
                    found |= self._parens(idx, src, sent, type_rank)
                prev_sentence = sent
            found_on_line.append(found)
        if table:
            self._table(idx, src, table, type_rank)
        if type_rank == 0:
            self._headings(idx, src, [t for t, _ in lines], found_on_line)

    def _clause(self, idx: int, src: Source, clause: str, type_rank: int, glossary_only: bool = False) -> bool:
        clause = clause.rstrip(".! ")
        if len(clause.split()) < 2:
            return False
        rank = type_rank * 10
        m = None if glossary_only else COPULA.match(clause)
        if m and _ok_term(m["term"]) and len(m["def"].split()) >= 3 and not _passive(m["def"]):
            if not m["def"].lower().startswith(("called ", "also ", "not ", "one of ", "why ")):
                self._add(Fact(m["term"], m["def"], _sentence(clause), "copula", src.title, idx, rank, 0,
                               blank=_sentence(clause.replace(m["term"], "____", 1))))
                return True
        split = None if glossary_only else _verb_split(clause)
        if split:
            term, definition = split
            self._add(Fact(term, definition, _sentence(clause), "verb", src.title, idx, rank, 0,
                           blank=_sentence(clause.replace(term, "____", 1))))
            return True
        m = GLOSSARY.match(clause)
        if m and _ok_term(m["term"]):
            definition = m["def"].strip()
            if m["paren"]:
                definition = f"{_sentence(definition)[:-1]} ({m['paren'].strip()})"
            if definition.split(" ", 1)[0].lower() not in _IMPERATIVE:
                self._add(Fact(m["term"], definition, _sentence(clause), "glossary", src.title, idx, rank, 0))
                return True
        return False

    def _parens(self, idx: int, src: Source, sent: str, type_rank: int) -> bool:
        found = False
        for m in PAREN.finditer(sent):
            term, definition = m["term"].strip(), m["def"].strip()
            letters = [w for w in _words(definition) if w.isalpha() and len(w) > 1]
            if len(letters) < 3 or not _ok_term(term) or definition.lower().startswith(("e.g", "see ", "like ", "for ")):
                continue
            blank = _sentence(sent.replace(f"{term} (", "____ (", 1))
            self._add(Fact(term, definition, _sentence(sent), "paren", src.title, idx,
                           type_rank * 10 + PATTERN_RANK["paren"], 0, blank=blank))
            found = True
        return found

    def _table(self, idx: int, src: Source, rows: list[list[str]], type_rank: int) -> None:
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) or not c for c in r)]
        if len(rows) < 2:
            return
        header, body = rows[0], rows[1:]
        for row in body:
            if len(row) < 2 or any(not c for c in row) or not _ok_term(row[0]):
                continue
            if len(row) == 2:
                definition = row[1]
            else:
                definition = "; ".join(f"{h}: {c}" if h else c for h, c in zip(header[1:], row[1:]))
            self._add(Fact(row[0], definition, _sentence(f"{row[0]}: {definition}"), "table", src.title, idx,
                           type_rank * 10, 0))

    def _headings(self, idx: int, src: Source, lines: list[str], found: list[bool]) -> None:
        for i, line in enumerate(lines[:-1]):
            words = line.split()
            if not (1 <= len(words) <= 5) or re.search(r"[.:;!?|,()\d]", line) or not line[0].isupper():
                continue
            term = re.sub(r"^(The|A|An) ", "", line)
            lw = [w.lower() for w in term.split()]
            if not _ok_term(term) or lw[0] in ("why", "how", "what") or any(w in _LABELS for w in lw):
                continue
            nxt = lines[i + 1]
            if found[i + 1] or not nxt.endswith(".") or len(nxt.split()) < 3 or "?" in nxt or "___" in nxt:
                continue
            parts = [nxt]
            j = i + 2
            while j < len(lines) and lines[j].split(" ", 1)[0].lower() in _CONT_VERBS and lines[j].endswith("."):
                parts.append(lines[j])
                j += 1
            definition = " ".join(parts)
            self._add(Fact(term, definition, f"{line}: {definition}", "heading", src.title, idx,
                           PATTERN_RANK["heading"], 0))

    def _reasons(self, idx: int, src: Source, sent: str, prev: str, type_rank: int) -> None:
        sent = sent.rstrip(" .")
        rank = type_rank * 10
        context = f"{_sentence(prev)} {_sentence(sent)}" if prev and re.match(r"^(This|That|These|It|They)\b", sent) \
            else _sentence(sent)

        def add(question: str, answer: str, terms: tuple[str, ...] = ()) -> None:
            self.pos += 1
            self.reasons.append(Reason(question, answer, answer, src.title, rank, self.pos, terms))

        m = THIS_IS_WHY.match(sent)
        if m and prev and "?" not in prev:
            add(f"Explain why {_lc_first(m['effect'], self.text)}.", f"{_sentence(prev)} {_sentence(sent)}")
            return
        m = BECAUSE.match(sent)
        if m and len(m["effect"].split()) >= 2 and len(m["cause"].split()) >= 2 \
                and m["effect"].split()[0].lower() not in _SUBJECT_STOP:
            add(f"Explain why {_lc_first(m['effect'], self.text)}.", context)
            return
        m = WHICH_LETS.match(sent)
        if m and len(m["effect"].split()) >= 2:
            if m["verb"] == "means":
                add(f"Explain why {_lc_first(m['effect'], self.text)}.", context)
            else:
                add(f"Explain what {m['verb']} {_lc_first(m['effect'], self.text)}.", context)
            return
        m = SO.match(sent)
        if m and len(m["effect"].split()) >= 2 and len(m["cause"].split()) >= 3 \
                and m["effect"].split()[0].lower() not in ("that", "it", "this"):
            add(f"Explain why {_lc_first(m['effect'], self.text)}.", context)
            return
        m = USES_TO.match(sent)
        if m and _ok_term(m["subj"]):
            subj = _lc_first(m["subj"], self.text, term=True)
            add(f"Explain why {subj} {m['verb']} {m['obj']}.", context, (norm_term(m["subj"]),))


def _dedupe(facts: list[Fact]) -> list[Fact]:
    seen_terms: set[str] = set()
    seen_defs: set[str] = set()
    out = []
    for f in sorted(facts, key=lambda f: (f.rank, f.pos)):
        d = " ".join(_words(f.definition.lower()))
        if f.key in seen_terms or d in seen_defs:
            continue
        seen_terms.add(f.key)
        seen_defs.add(d)
        out.append(f)
    return out


def _pick_cards(facts: list[Fact], count: int) -> list[Fact]:
    """Best ranks first; within a rank, take turns between files so every file is covered."""
    chosen: list[Fact] = []
    for rank in sorted({f.rank for f in facts}):
        by_file: dict[int, list[Fact]] = {}
        for f in sorted((f for f in facts if f.rank == rank), key=lambda f: f.pos):
            by_file.setdefault(f.file_idx, []).append(f)
        queues = [by_file[k] for k in sorted(by_file)]
        while any(queues) and len(chosen) < count:
            for q in queues:
                if q and len(chosen) < count:
                    chosen.append(q.pop(0))
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda f: f.pos)


def _contrast_pairs(facts: list[Fact]) -> list[tuple[Fact, Fact]]:
    """hypotonic / hypertonic, prokaryotes / eukaryotes, passive / active transport ..."""
    pairs = []
    for i, a in enumerate(facts):
        for b in facts[i + 1:]:
            wa, wb = a.term.lower().split(), b.term.lower().split()
            if len(wa) > 1 and len(wb) > 1 and wa[-1] == wb[-1] and wa[:-1] != wb[:-1]:
                pairs.append((a, b))
                continue
            x, y = wa[0], wb[0]
            n = 0
            while n < min(len(x), len(y)) and x[-1 - n] == y[-1 - n]:
                n += 1
            suffix = x[len(x) - n:]
            if (n >= 4 and x != y and n >= 0.5 * min(len(x), len(y)) and len(x) - n <= 6 and len(y) - n <= 6
                    and not suffix.endswith(_COMMON_SUFFIXES)):
                pairs.append((a, b))
    return pairs


def _choice(fact: Fact, pool: list[Fact]) -> dict[str, Any] | None:
    correct = fact.term
    others = []
    for f in pool:
        a, b = f.term.lower(), correct.lower()
        if f.key == fact.key or a in b or b in a or f.definition == fact.definition:
            continue
        others.append(f)
    if len(others) < 2:
        return None
    plural = _is_plural(correct)
    others.sort(key=lambda f: (_is_plural(f.term) != plural, abs(len(f.term.split()) - len(correct.split())),
                               stable_hash(correct + "|" + f.term)))
    distractors = [_cap(f.term) for f in others[:3]]
    n = len(distractors) + 1
    at = stable_hash(correct) % n
    options = [{"text": d, "correct": False} for d in distractors]
    options.insert(at, {"text": _cap(correct), "correct": True})
    return {"text": f"Which term matches this description? {fact.definition}", "kind": "choice",
            "options": options, "source": fact.source}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _explain_fallback(fact: Fact) -> dict[str, Any]:
    pronoun, verb, matter = ("they", "do", "they matter") if _is_plural(fact.term) else ("it", "does", "it matters")
    what = f"what {pronoun} {verb}" if fact.kind == "verb" else f"what {pronoun} {'are' if pronoun == 'they' else 'is'}"
    return {"text": f"{_cap(fact.term)}: explain {what} and why {matter}.", "kind": "explain",
            "answer": f"{_cap(fact.term)}: {fact.definition}", "rubric": fact.sentence, "source": fact.source}


# ---------------------------------------------------------------- the package
def build_package(sources: list[Source], *, card_count: int = 10, mc_count: int = 4,
                  explain_count: int = 2) -> dict[str, Any]:
    """Deterministic package draft: {flashcards, fill_in, questions} (matching is made from the
    flashcards when the package is saved). Raises NotEnoughMaterial when < MIN_CARDS terms."""
    ex = _Extractor(sources).run()
    facts = _dedupe(ex.facts)
    if len(facts) < MIN_CARDS:
        raise NotEnoughMaterial(
            f"Only found {len(facts)} key term(s) with a definition in this unit's notes and readings "
            f"(need at least {MIN_CARDS}). Add notes or slides that define the unit's terms "
            "(e.g. \"Osmosis: water moving across a membrane\"), or add an AI key for the games agent.")
    cards = _pick_cards(facts, card_count)

    flashcards = [{"front": _cap(f.term), "back": f.definition, "source": f.source} for f in cards]

    n_games = min(len(cards), MAX_GAME_ITEMS, max(card_count, MIN_CARDS))
    with_blank = [f for f in cards if f.blank and "____" in f.blank
                  and not re.search(rf"\b{re.escape(f.term)}\b", f.blank, re.IGNORECASE)]
    rest = [f for f in cards if f not in with_blank]
    fill_in = []
    for f in sorted((with_blank + rest)[:n_games], key=lambda f: f.pos):
        sentence = f.blank if f in with_blank else f"____: {f.definition}"
        fill_in.append({"sentence": sentence, "answer": f.term, "alternates": alternates(f.term, ex.text),
                        "source": f.source})

    # Check-in: explain questions first (so MC can avoid their terms), then MC.
    explain: list[dict[str, Any]] = []
    used_terms: set[str] = set()
    seen_q: set[str] = set()
    for r in sorted(ex.reasons, key=lambda r: (r.rank, r.pos)):
        if len(explain) >= explain_count:
            break
        if r.question.lower() in seen_q:
            continue
        seen_q.add(r.question.lower())
        explain.append({"text": r.question, "kind": "explain", "answer": r.answer, "rubric": r.sentence,
                        "source": r.source})
        used_terms.update(r.terms)
    for a, b in _contrast_pairs(cards) + _contrast_pairs(facts):
        if len(explain) >= explain_count:
            break
        if a.key in used_terms or b.key in used_terms:
            continue
        q = f"Explain the difference between {_lc_first(a.term, ex.text, True)} and {_lc_first(b.term, ex.text, True)}."
        if q.lower() in seen_q:
            continue
        seen_q.add(q.lower())
        both = f"{_cap(a.term)}: {a.definition} {_cap(b.term)}: {b.definition}"
        explain.append({"text": q, "kind": "explain", "answer": both, "rubric": f"{a.sentence} {b.sentence}",
                        "source": a.source if a.source == b.source else f"{a.source}; {b.source}"})
        used_terms.update({a.key, b.key})
    for f in sorted(cards, key=lambda f: (f.kind != "verb", -len(f.definition), f.pos)):
        if len(explain) >= explain_count:
            break
        if f.key in used_terms:
            continue
        explain.append(_explain_fallback(f))
        used_terms.add(f.key)

    mc: list[dict[str, Any]] = []
    order = sorted(cards, key=lambda f: (f.key in used_terms, len(f.definition.split()) < 3, f.kind == "heading", f.pos))
    order += [f for f in sorted(facts, key=lambda f: f.pos) if f not in cards]
    for f in order:
        if len(mc) >= mc_count:
            break
        q = _choice(f, facts)
        if q:
            mc.append(q)

    return {"flashcards": flashcards, "fill_in": fill_in, "questions": mc + explain}


def _blank_ok(f: Fact) -> bool:
    return bool(f.blank) and "____" in f.blank and not re.search(rf"\b{re.escape(f.term)}\b", f.blank, re.IGNORECASE)


def candidate_pool(sources: list[Source]) -> dict[str, list[dict[str, Any]]]:
    """Everything the no-AI generator can make from these sources, best first, with no count
    limits: the supply for "Regenerate this one" (editing.py). Same text, same pool. The package's
    own items are in it too, so callers skip what's already used.

        {"cards": [{front, back, source}], "fill_in": [{sentence, answer, alternates, source}],
         "choice": [{text, kind, options, source}], "explain": [{text, kind, answer, rubric, source}]}

    Empty lists (never NotEnoughMaterial) when the text holds too few terms."""
    ex = _Extractor(sources).run()
    facts = _dedupe(ex.facts)                     # already in (rank, pos) order
    if len(facts) < 2:
        return {"cards": [], "fill_in": [], "choice": [], "explain": []}
    cards = [{"front": _cap(f.term), "back": f.definition, "source": f.source} for f in facts]
    fill_in = [{"sentence": f.blank if _blank_ok(f) else f"____: {f.definition}", "answer": f.term,
                "alternates": alternates(f.term, ex.text), "source": f.source}
               for f in sorted(facts, key=lambda f: not _blank_ok(f))]          # real blanks first
    choice = []
    for f in sorted(facts, key=lambda f: (f.rank, len(f.definition.split()) < 3, f.kind == "heading", f.pos)):
        q = _choice(f, facts)
        if q:
            choice.append(q)
    explain: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(q: dict[str, Any]) -> None:
        if q["text"].lower() not in seen:
            seen.add(q["text"].lower())
            explain.append(q)

    for r in sorted(ex.reasons, key=lambda r: (r.rank, r.pos)):
        add({"text": r.question, "kind": "explain", "answer": r.answer, "rubric": r.sentence, "source": r.source})
    for a, b in _contrast_pairs(facts):
        add({"text": f"Explain the difference between {_lc_first(a.term, ex.text, True)} and "
                     f"{_lc_first(b.term, ex.text, True)}.", "kind": "explain",
             "answer": f"{_cap(a.term)}: {a.definition} {_cap(b.term)}: {b.definition}",
             "rubric": f"{a.sentence} {b.sentence}",
             "source": a.source if a.source == b.source else f"{a.source}; {b.source}"})
    for f in sorted(facts, key=lambda f: (f.kind != "verb", -len(f.definition), f.pos)):
        add(_explain_fallback(f))
    return {"cards": cards, "fill_in": fill_in, "choice": choice, "explain": explain}


def matching_from_cards(cards: list[dict[str, Any]], limit: int = MAX_GAME_ITEMS) -> list[dict[str, Any]]:
    """Matching pairs from the (reviewed) flashcards: the shortest definitions, in card order."""
    ranked = sorted(range(len(cards)), key=lambda i: (len(cards[i]["back"]), i))[:limit]
    return [{"term": cards[i]["front"], "definition": cards[i]["back"], "source": cards[i].get("source")}
            for i in sorted(ranked)]
