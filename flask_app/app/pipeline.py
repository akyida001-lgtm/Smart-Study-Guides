"""End-to-end generation pipeline. Runs in a background thread."""
import threading
import traceback
from datetime import datetime
from flask import current_app

from .models import db, Assignment, User, PipelineLog
from .prompts import GENERATION_PROMPT, FORMATTING_PROMPT, _STYLE_RULES, _DEFAULT_STYLE_RULE
from .services import openai_service, ryter_service, supabase_storage, email_service
from .services.openai_service import format_source_with_ai
from .services.docx_builder import build_docx


PIPELINE_STEPS = [
    ("Generating draft", 10),
    ("Humanizing", 25),
    ("Checking AI score", 40),
    ("Re-humanizing", 55),
    ("Formatting", 75),
    ("Building document", 85),
    ("Uploading", 92),
    ("Sending email", 97),
    ("Done", 100),
]


def _log(assignment_id: int, step: str, status: str = "info", detail: str = ""):
    db.session.add(PipelineLog(
        assignment_id=assignment_id, step=step, status=status, detail=detail or None
    ))
    db.session.commit()


def _set_progress(a: Assignment, step: str, percent: int):
    a.progress_step = step
    a.progress_percent = percent
    db.session.commit()


def _format_sources_block(sources):
    """Build the sources block for the generation prompt.
    Prefers Step-2b annotation data (apa_intext, apa_reference, annotation),
    then AI-formatted raw_text, then raw metadata as fallback."""
    blocks = []
    for i, s in enumerate(sources, 1):
        if s.apa_reference and s.annotation:
            # Rich annotation from Step 2b — give the model everything it needs
            blocks.append(
                f"--- Source {i} ---\n"
                f"Title   : {s.title or 'Untitled'}\n"
                f"Authors : {s.authors or 'Unknown'}\n"
                f"Year    : {s.year or 'n.d.'}\n"
                f"URL     : {s.url or ''}\n"
                f"In-text : {s.apa_intext or ''}\n"
                f"Reference entry:\n{s.apa_reference}\n"
                f"Formal paragraph (use this content when writing about this source):\n{s.annotation}\n"
            )
        elif s.raw_text:
            blocks.append(f"--- Source {i} ---\n{s.raw_text}\n")
        else:
            blocks.append(
                f"--- Source {i} ---\n"
                f"Title  : {s.title or 'Untitled'}\n"
                f"URL    : {s.url or ''}\n"
                f"Summary: {s.summary or ''}\n"
            )
    return "\n".join(blocks)


_OPEN_PROMPT = """\
You are a skilled academic writer. A student has provided the following task, question, or scenario.
Write a complete, well-structured response of approximately {word_count} words.
Write at the level of a {level} student — clear, organised, thoughtful.
Do NOT add a references section unless the task explicitly asks for one.
Do NOT use any preamble like "Sure, here is..." — begin the response directly.

Task / Instructions:
{topic}
"""


def _run_open_pipeline(app, a, user):
    """Pipeline for Open Task assignments — no sources, optional image sent to Vision API."""
    try:
        a.status = "running"
        db.session.commit()

        # Step 1: Generate using Vision if image provided, else plain chat
        _set_progress(a, "Generating response", 10)
        _log(a.id, "Generating (open)", "start")
        prompt = _OPEN_PROMPT.format(
            word_count=a.word_count,
            level=a.education_level or "Undergraduate",
            topic=a.topic,
        )
        if getattr(a, "instruction_image_url", None):
            paper = openai_service.chat_with_image(prompt, a.instruction_image_url, max_tokens=8000)
        else:
            paper = openai_service.chat(prompt, max_tokens=8000)
        _log(a.id, "Generating (open)", "done", f"{len(paper)} chars")

        # Step 2: Humanize loop with Ryter Pro
        humanized = paper
        ai_score  = 100.0
        for attempt in range(1, 6):
            _set_progress(a, f"Humanizing (attempt {attempt})", 20 + attempt * 8)
            _log(a.id, "Humanizing", "start", f"attempt {attempt}")
            humanized = ryter_service.humanize(
                humanized,
                style=getattr(a, "humanize_style", None) or "academic",
                model=getattr(a, "humanize_model", None) or "premium",
            )
            _log(a.id, "Humanizing", "done", f"{len(humanized)} chars")
            _set_progress(a, f"Checking AI score (attempt {attempt})", 30 + attempt * 8)
            ai_score = ryter_service.detect_ai_score(humanized)
            _log(a.id, "AI detection", "done", f"score={ai_score}")
            if ai_score <= 0:
                break

        # Step 3: Light formatting (no citations)
        _set_progress(a, "Formatting", 75)
        simple_fmt = (
            "You are an academic editor. Lightly format the text below into clean, well-structured paragraphs. "
            "Do NOT add citations or a reference list. Preserve all content. Output only the formatted text.\n\n"
            + humanized
        )
        final_text = openai_service.chat(simple_fmt, max_tokens=8000)
        a.paper_text = final_text
        db.session.commit()

        # Step 4: Build DOCX
        _set_progress(a, "Building document", 85)
        _log(a.id, "Building DOCX", "start")
        docx_bytes = build_docx(
            title=a.topic[:80],
            student_name=a.student_name or user.display_name,
            course_name=a.course_name or "",
            school_name=getattr(a, "school_name", "") or "",
            instructor_name=getattr(a, "instructor_name", "") or "",
            due_date=getattr(a, "due_date", "") or "",
            body_text=final_text,
            sources=[],
        )
        _log(a.id, "Building DOCX", "done")

        # Step 5: Upload
        _set_progress(a, "Uploading", 92)
        import time as _t
        filename = f"docx_{a.id}_{int(_t.time())}.docx"
        url = supabase_storage.upload_docx(filename, docx_bytes)
        a.docx_url = url
        a.docx_filename = filename
        _log(a.id, "Uploading", "done")

        # Step 6: Email
        _set_progress(a, "Sending email", 97)
        try:
            email_service.send_assignment_ready(
                to_email=user.email,
                student_name=user.display_name,
                topic=a.topic,
                docx_url=url,
            )
        except Exception as exc:
            _log(a.id, "Email", "warn", str(exc))

        a.status = "done"
        a.completed_at = datetime.utcnow()
        _set_progress(a, "Done", 100)
        _log(a.id, "Pipeline (open)", "done")

    except Exception as exc:
        a.status = "failed"
        a.error_message = str(exc)
        db.session.commit()
        _log(a.id, "Pipeline (open)", "error", traceback.format_exc()[:1000])


def run_pipeline(app, assignment_id: int):
    with app.app_context():
        a = Assignment.query.get(assignment_id)
        if not a:
            return

        # Route open-task and simple (no-citation) assignments to dedicated pipeline
        if getattr(a, "assignment_type", "standard") in ("open", "simple"):
            user = User.query.get(a.user_id)
            _run_open_pipeline(app, a, user)
            return

        try:
            a.status = "running"
            db.session.commit()

            user = User.query.get(a.user_id)

            # Step 0: AI-format each auto-fetched source that hasn't been formatted yet
            auto_sources = [s for s in a.sources if not s.is_user_provided and not s.raw_text]
            if auto_sources:
                _set_progress(a, "Formatting sources", 3)
                _log(a.id, "Formatting sources", "start", f"{len(auto_sources)} sources")
                for s in auto_sources:
                    try:
                        s.raw_text = format_source_with_ai(
                            title=s.title or "",
                            authors=s.authors or "",
                            year=s.year,
                            url=s.url or "",
                            abstract=s.summary or "",
                            citation_style=a.style,
                        )
                    except Exception as exc:
                        _log(a.id, "Formatting sources", "warn", f"source {s.id}: {exc}")
                db.session.commit()
                _log(a.id, "Formatting sources", "done")

            sources_text = _format_sources_block(a.sources)

            # Step 1: Generation
            _set_progress(a, "Generating draft", 10)
            _log(a.id, "Generating draft", "start")
            # Resolve citation style rule block
            citation_rule = _STYLE_RULES.get(
                a.style,
                _DEFAULT_STYLE_RULE.replace("[CITATION_STYLE]", a.style or "APA")
            )

            gen_prompt = (
                GENERATION_PROMPT
                .replace("[CITATION_RULE_BLOCK]", citation_rule)
                .replace("[WORD_COUNT]", str(a.word_count))
                .replace("[NUM_PAGES]", str(a.pages))
                .replace("[ASSIGNMENT_TOPIC]", a.topic)
                .replace("[SOURCES]", sources_text)
                .replace("[STUDENT_NAME]", a.student_name or user.display_name)
                .replace("[COURSE_NAME]", a.course_name or "")
                .replace("[SCHOOL_NAME]", a.school_name or "")
                .replace("[INSTRUCTOR_NAME]", a.instructor_name or "")
                .replace("[DUE_DATE]", a.due_date or "")
            )
            paper = openai_service.chat(gen_prompt, max_tokens=8000)
            _log(a.id, "Generating draft", "done", f"{len(paper)} chars")

            # Steps 2 + 3: Humanize and check AI score, repeat up to 5 times
            humanized = paper
            ai_score = 100.0
            attempts = 0
            max_attempts = 5
            while attempts < max_attempts:
                attempts += 1
                _set_progress(a, f"Humanizing (attempt {attempts})", 25 + attempts * 4)
                _log(a.id, "Humanizing", "start", f"attempt {attempts}")
                humanized = ryter_service.humanize(
                    humanized,
                    style=getattr(a, "humanize_style", None) or "academic",
                    model=getattr(a, "humanize_model", None) or "premium",
                )
                _log(a.id, "Humanizing", "done", f"{len(humanized)} chars")

                _set_progress(a, f"Checking AI score (attempt {attempts})", 40 + attempts * 4)
                _log(a.id, "AI detection", "start", f"attempt {attempts}")
                ai_score = ryter_service.detect_ai_score(humanized)
                _log(a.id, "AI detection", "done", f"score={ai_score}")
                if ai_score <= 0:
                    break

            # Step 5: Formatting
            _set_progress(a, "Formatting", 75)
            _log(a.id, "Formatting", "start")
            fmt_prompt = FORMATTING_PROMPT.replace("[PAPER]", humanized)
            final_text = openai_service.chat(fmt_prompt, max_tokens=8000)
            _log(a.id, "Formatting", "done", f"{len(final_text)} chars")

            # Store the final paper text for rubric marking later
            a.paper_text = final_text
            db.session.commit()

            # Step 6: Build DOCX
            _set_progress(a, "Building document", 85)
            docx_bytes = build_docx(
                final_text, a.topic,
                course_name=a.course_name or "",
                student_name=a.student_name or user.display_name,
                instructor_name=a.instructor_name or "",
                school_name=a.school_name or "",
                due_date=a.due_date or "",
            )
            filename = f"assignment_{a.id}_{int(datetime.utcnow().timestamp())}.docx"
            a.docx_filename = filename

            # Step 7: Upload to Supabase
            _set_progress(a, "Uploading", 92)
            _log(a.id, "Uploading", "start")
            try:
                url = supabase_storage.upload_docx(filename, docx_bytes)
                a.docx_url = url
                _log(a.id, "Uploading", "done", url[:120])
            except Exception as e:
                _log(a.id, "Uploading", "error", str(e))
                raise

            # Step 8: Email notification
            _set_progress(a, "Sending email", 97)
            try:
                if user and user.email:
                    email_service.send_assignment_ready_email(
                        user.email, user.display_name, a.topic[:80], a.docx_url
                    )
                _log(a.id, "Email", "done")
            except Exception as e:
                _log(a.id, "Email", "error", str(e))

            # Step 9: Deduct credits
            if user:
                user.credits = max(0, (user.credits or 0) - a.credit_cost)
                db.session.commit()
                _log(a.id, "Credits", "done", f"deducted {a.credit_cost}")

            a.status = "complete"
            a.completed_at = datetime.utcnow()
            _set_progress(a, "Done", 100)
            _log(a.id, "Pipeline", "complete")

        except Exception as e:
            current_app.logger.exception("Pipeline failed")
            a.status = "failed"
            a.error_message = f"{type(e).__name__}: {str(e)[:500]}"
            a.progress_step = f"Failed: {a.error_message[:80]}"
            db.session.commit()
            _log(a.id, "Pipeline", "error", traceback.format_exc()[:2000])


def start_pipeline(app, assignment_id: int):
    t = threading.Thread(target=run_pipeline, args=(app, assignment_id), daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────────────────────────
# Finalization pipeline — runs AFTER the draft has already been written live.
# Input: assignment.paper_text is set, status is "draft_ready".
# Steps: Humanize → Format → DOCX → Upload → Email → Credits → Done
# ─────────────────────────────────────────────────────────────────────────────

def run_finalize_pipeline(app, assignment_id: int):
    with app.app_context():
        a = Assignment.query.get(assignment_id)
        if not a:
            return
        try:
            a.status = "running"
            db.session.commit()

            user = User.query.get(a.user_id)
            paper = a.paper_text or ""
            if not paper:
                raise RuntimeError("No draft text to finalize.")

            # Step 1: Humanize loop
            humanized = paper
            ai_score = 100.0
            for attempt in range(1, 6):
                _set_progress(a, f"Humanizing (attempt {attempt})", 10 + attempt * 10)
                _log(a.id, "Humanizing", "start", f"attempt {attempt}")
                humanized = ryter_service.humanize(
                    humanized,
                    style=getattr(a, "humanize_style", None) or "academic",
                    model=getattr(a, "humanize_model", None) or "premium",
                )
                _log(a.id, "Humanizing", "done", f"{len(humanized)} chars")

                _set_progress(a, f"Checking AI score (attempt {attempt})", 20 + attempt * 10)
                _log(a.id, "AI detection", "start", f"attempt {attempt}")
                ai_score = ryter_service.detect_ai_score(humanized)
                _log(a.id, "AI detection", "done", f"score={ai_score}")
                if ai_score <= 0:
                    break

            # Step 2: Format
            _set_progress(a, "Formatting", 75)
            _log(a.id, "Formatting", "start")
            fmt_prompt = FORMATTING_PROMPT.replace("[PAPER]", humanized)
            final_text = openai_service.chat(fmt_prompt, max_tokens=8000)
            _log(a.id, "Formatting", "done", f"{len(final_text)} chars")

            a.paper_text = final_text
            db.session.commit()

            # Step 3: Build DOCX
            _set_progress(a, "Building document", 85)
            docx_bytes = build_docx(
                final_text, a.topic,
                course_name=a.course_name or "",
                student_name=a.student_name or user.display_name,
                instructor_name=a.instructor_name or "",
                school_name=a.school_name or "",
                due_date=a.due_date or "",
            )
            filename = f"assignment_{a.id}_{int(datetime.utcnow().timestamp())}.docx"
            a.docx_filename = filename

            # Step 4: Upload
            _set_progress(a, "Uploading", 92)
            _log(a.id, "Uploading", "start")
            try:
                url = supabase_storage.upload_docx(filename, docx_bytes)
                a.docx_url = url
                _log(a.id, "Uploading", "done", url[:120])
            except Exception as e:
                _log(a.id, "Uploading", "error", str(e))
                raise

            # Step 5: Email
            _set_progress(a, "Sending email", 97)
            try:
                if user and user.email:
                    email_service.send_assignment_ready_email(
                        user.email, user.display_name, a.topic[:80], a.docx_url
                    )
                _log(a.id, "Email", "done")
            except Exception as e:
                _log(a.id, "Email", "error", str(e))

            # Step 6: Deduct credits
            if user:
                user.credits = max(0, (user.credits or 0) - a.credit_cost)
                db.session.commit()
                _log(a.id, "Credits", "done", f"deducted {a.credit_cost}")

            a.status = "complete"
            a.completed_at = datetime.utcnow()
            _set_progress(a, "Done", 100)
            _log(a.id, "Pipeline", "complete")

        except Exception as e:
            current_app.logger.exception("Finalize pipeline failed")
            a.status = "failed"
            a.error_message = f"{type(e).__name__}: {str(e)[:500]}"
            a.progress_step = f"Failed: {a.error_message[:80]}"
            db.session.commit()
            _log(a.id, "Pipeline", "error", traceback.format_exc()[:2000])


def start_finalize_pipeline(app, assignment_id: int):
    t = threading.Thread(target=run_finalize_pipeline, args=(app, assignment_id), daemon=True)
    t.start()
