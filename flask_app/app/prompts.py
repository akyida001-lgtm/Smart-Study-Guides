"""Exact prompts for the assignment generation pipeline."""

# ── Per-source formatting (Step 2b uses generate_source_annotations instead) ──

PER_SOURCE_PROMPT = """You are an academic research assistant. Format the following real source into the required academic structure using [CITATION_STYLE] citation style.

SOURCE DETAILS:
Title: [TITLE]
Authors: [AUTHORS]
Year: [YEAR]
URL: [URL]
Abstract: [ABSTRACT]

Output using exactly this structure (no extra text, no preamble):

1. Article Topic
[Write the main topic or title of the article]

2. In-text Citation ([CITATION_STYLE] Style)
[Provide the in-text citation exactly as it would appear in a paragraph, formatted correctly for [CITATION_STYLE]]

3. Full [CITATION_STYLE] Reference + Accurate URL
[Write the complete reference entry formatted correctly for [CITATION_STYLE], then on a new line write the URL exactly as provided]

4. 200-Word Paragraph (Formal Tone, Not a Summary)
[Write one formal academic-style paragraph of around 200 words. Cover: the core argument or purpose of the article; the main ideas, themes, or evidence presented; the perspective or position the article takes; the key points or contributions to the topic. Use a presentational and formal tone — not a summary tone. Do not analyze or critique; focus on what the article presents and emphasizes.]

Rules:
- Use only the information provided above — do not invent facts, authors, or dates
- Use the exact URL provided
- Follow [CITATION_STYLE] format exactly for all citations and references
- Use a presentational and formal tone throughout
"""


# ── Style-specific citation rules injected into GENERATION_PROMPT ─────────────

_STYLE_RULES = {
    "APA": """\
Citation style: APA 7th Edition
- In-text: parenthetical (Author, Year) — e.g. (Smith et al., 2023)
- Placement: supporting/evidence sentences only — NEVER in the topic sentence or concluding sentence of a paragraph
- References page title: "References" (centred, bold)
- List all sources alphabetically by first author's last name in APA 7 format
- Sources must be from 2020–2025 only""",

    "MLA": """\
Citation style: MLA 9th Edition
- In-text: parenthetical (Author Page) — e.g. (Smith 45) or (Smith et al. 112)
- If no page number, use paragraph number or omit: (Smith)
- Placement: supporting/evidence sentences only — NEVER in the topic sentence or concluding sentence
- Works Cited page title: "Works Cited" (centred)
- List all sources alphabetically in MLA 9 hanging-indent format
- Sources must be from 2020–2025 only""",

    "Chicago": """\
Citation style: Chicago 17th Edition (Author-Date)
- In-text: parenthetical (Author Year, page) — e.g. (Smith 2023, 45)
- Placement: supporting/evidence sentences only — NEVER in the topic sentence or concluding sentence
- Bibliography title: "Bibliography" (centred)
- List all sources alphabetically in Chicago Author-Date format
- Sources must be from 2020–2025 only""",

    "Harvard": """\
Citation style: Harvard Referencing Style
- In-text: parenthetical (Author Year, p. page) — e.g. (Smith 2023, p. 45) or (Smith 2023)
- Placement: supporting/evidence sentences only — NEVER in the topic sentence or concluding sentence
- Reference list title: "References" (centred)
- List all sources alphabetically in Harvard format
- Sources must be from 2020–2025 only""",
}

_DEFAULT_STYLE_RULE = """\
Citation style: [CITATION_STYLE]
- Use correct in-text citations for [CITATION_STYLE] in supporting/evidence sentences only
- Include a properly formatted reference list at the end
- Sources must be from 2020–2025 only"""


# ── Main generation prompt ─────────────────────────────────────────────────────

GENERATION_PROMPT = """Assume you are the student responsible for completing this assignment.
Your task is to create a perfect, complete, and fully accurate response that strictly follows the assignment instructions step by step.
Do not skip any part of the task. Do not include generalizations, assumptions, or made-up content.
Everything must be real, specific, true, and directly based on the sources provided.
The structure, content, tone, and formatting must match the expectations of the specific assignment type (e.g., essay, report, journal, presentation).

════════════════════════════════════════
MANDATORY STRUCTURE (follow in this exact order)
════════════════════════════════════════

1. TITLE PAGE
   Include all of the following on separate lines:
   - Assignment title / topic
   - Student Name: [STUDENT_NAME]
   - Institution: [SCHOOL_NAME]
   - Course: [COURSE_NAME]
   - Instructor: [INSTRUCTOR_NAME]
   - Date: [DUE_DATE]

2. INTRODUCTION PARAGRAPH
   Follow this exact 3-part structure:
   → HOOK: Begin with a compelling sentence that engages the reader (a striking fact, question, or statement related to the topic)
   → BACKGROUND: 2–3 sentences providing context and relevant background information on the topic
   → THESIS: End with a clear, focused thesis statement. Start it with: "This paper shows that…"
   Do NOT include multiple purpose statements. The introduction is one paragraph only.

3. MAIN CONTENT / BODY SECTION
   - Address ALL parts of the assignment instructions step by step, in order
   - If the assignment gives subheadings, questions, or subtopics — use them EXACTLY as written (do not rephrase or rename them)
   - Every body paragraph must have exactly 4 or 5 sentences, structured as follows:
       → Topic sentence — states the main idea of the paragraph
       → Supporting sentence(s) — add detail and explanation
       → Development — expand with facts, examples, evidence, or reasoning drawn from the sources
       → Coherence — keep sentences logically connected
       → Concluding sentence — summarises or wraps up the paragraph
   - Use full sentences throughout unless bullet points are explicitly required by the assignment instructions

4. CONCLUSION PARAGRAPH
   - Restate the thesis in different words
   - Summarise the key points made in the body
   - End with a closing thought, implication, or recommendation
   - Do not introduce new arguments or citations in the conclusion

5. REFERENCES / WORKS CITED / BIBLIOGRAPHY
   [CITATION_RULE_BLOCK]

════════════════════════════════════════
CITATION RULES
════════════════════════════════════════
[CITATION_RULE_BLOCK]

════════════════════════════════════════
LENGTH REQUIREMENT
════════════════════════════════════════
Total word count: exactly [WORD_COUNT] words ([NUM_PAGES] pages at ~275 words per page).
Write enough body paragraphs to reach this word count. Do not stop short.

════════════════════════════════════════
ASSIGNMENT INSTRUCTIONS
════════════════════════════════════════
[ASSIGNMENT_TOPIC]

════════════════════════════════════════
SOURCES — USE ONLY THESE
════════════════════════════════════════
[SOURCES]

════════════════════════════════════════
FINAL CHECKLIST BEFORE OUTPUTTING
════════════════════════════════════════
✅ Title page present with all student details
✅ Introduction has hook → background → thesis ("This paper shows that…")
✅ Every body paragraph has exactly 4–5 sentences in the correct structure
✅ Subheadings/questions used exactly as given — not rephrased
✅ In-text citations appear only in supporting/evidence sentences (not in topic or concluding sentences)
✅ All citations come only from the approved sources list above
✅ Reference list is complete and correctly formatted
✅ Total word count is [WORD_COUNT] words
✅ Formal, informative, and explanatory tone throughout
✅ Output is complete and ready to submit — no placeholders, no gaps

The final output must be complete, correct, and professionally formatted — ready to submit with no edits needed.
"""


MARKING_PROMPT = """You are an academic assessor. Your task is to mark the student paper below strictly against the criteria stated in the rubric provided.

CRITICAL RULES:
- Mark ONLY based on criteria in the rubric — nothing else
- Do NOT penalise for grammar, spelling, or sentence flow — the paper was machine-humanized so grammar may be imperfect; this is expected and must be ignored entirely
- Be fair, specific, and constructive in feedback
- If the rubric provides a points/marks allocation, use it exactly
- If a criterion is not addressed in the paper, note it clearly

OUTPUT FORMAT — use exactly this structure:

## Rubric Assessment

[For each criterion found in the rubric:]
**[Criterion]** — [Score earned / Score possible if provided]
[2–3 sentences of specific, evidence-based feedback referencing the paper]

---

## Overall Feedback
[2–3 paragraphs covering: what was done well, what could be improved, and how closely the paper met the rubric requirements]

## Total Score
[X / Y marks] — [Brief overall verdict: Excellent / Good / Satisfactory / Needs Improvement]

---

RUBRIC:
[RUBRIC_CONTENT]

STUDENT PAPER:
[PAPER_TEXT]
"""


FORMATTING_PROMPT = """You are a professional academic editor. Take the following academic paper and produce a final, polished, professionally formatted version.
Preserve all content, citations, references, and the existing structure exactly.
Improve sentence flow, fix any small grammatical issues, and ensure a consistent formal academic tone throughout.
Do not shorten, summarise, or remove any section. Do not remove or alter any citations or references.
Output only the final formatted paper — no commentary, no preamble.

Paper:
[PAPER]
"""


DOCX_FORMATTING_PROMPT = """You are a professional academic document formatter. Your job is to prepare the paper below so it can be converted into a correctly formatted Word document.

FORMATTING STANDARDS (apply exactly):
- Font: Times New Roman 12pt throughout
- Spacing: Double spaced throughout
- Paragraph indent: 0.5 inch first-line indent on every body paragraph
- Headings and subheadings: bold and centred
- References / Works Cited / Bibliography: must appear on a completely new last page with 0.5-inch hanging indent on each entry
- Academic quality: high — preserve all citations, arguments, and evidence exactly

STRUCTURE MARKERS — use these EXACTLY so the Word builder can parse the document correctly:

Use  # HEADING  (hash + space + uppercase name) for main section headings:
  # INTRODUCTION
  # BODY
  # CONCLUSION
  # REFERENCES        ← this triggers a page break and hanging-indent formatting

Use  ## Subheading  (double-hash) for subheadings inside sections.

Use  ## REFERENCES  or  # REFERENCES  or just  REFERENCES  on its own line to mark the start of the reference list — place it at the very end.

RULES:
1. Do NOT change any academic content, citations, arguments, or wording
2. Do NOT add placeholder text or commentary
3. Remove any duplicate title page text — the Word builder adds the title page automatically
4. Preserve every reference entry exactly — just place them under the REFERENCES marker
5. Output ONLY the structured paper body (introduction through references) — no preamble, no "here is the formatted paper" commentary

PAPER TO FORMAT:
[PAPER]
"""
