# Smart Study Guides: read this first

## Hosting (this is settled, do not re-ask)
- **Web host: Vercel** (Python / Flask, serverless functions). Entry point: `flask_app.main:app`, set in `pyproject.toml` under `[tool.vercel]`.
- **Database: Neon** (serverless Postgres), connected through `DATABASE_URL`.
- **File storage: Cloudflare R2** for feed photos and videos (`R2_ENDPOINT_URL`, `R2_PUBLIC_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, optional `R2_BUCKET`).
- Other services: Stripe (payments), Resend (email), Twilio (SMS), OpenAI.
- **It is NOT on Fly.io, Docker, Heroku or Replit.** `fly.toml`, `Dockerfile` and `.dockerignore` were leftovers and have been removed.
  Some Replit-era names still exist in code (`REPLIT_DOMAINS`, `replit_auth.py`, "Replit AI proxy"). They are old names only, not the host.

## What Vercel and Neon mean for the code
- A request body to a function cannot exceed about **4.5 MB**. Larger uploads must go **from the browser straight to R2** with a presigned URL
  (this is what `app/feed.py` and `static/js/feed.js` do for videos over about 3.5 MB). The R2 bucket must allow `PUT` from the site's origin (CORS).
- The file system is **read-only, except a temporary `/tmp`, and nothing there lasts.** Never save user files to disk in production.
- Functions are short-lived: **no background threads or long jobs** inside a request; respect the function time limit.
- Every request may start a fresh instance: keep the database pool small and keep `pool_pre_ping`. Prefer Neon's pooled connection string.
- The real site needs the Neon `DATABASE_URL`, so it cannot be run fully on a machine without it. Test templates and CSS in isolation instead.

## Design decisions already made (do not undo)
- The signed-out Dashboard and the signed-in Dashboard are the same page (`templates/home.html`). It must fit one screen with no scrolling.
- Signed-in and signed-out users share one header and menu (`templates/_site_nav.html`). Only the Sign in spot differs.
- The header is fixed on phones. The brand name is not repeated inside page bodies (it is already in the header and footer).

## Uploads (admin)
- **Updates (`/updates`)**: admin ("staff") posts can have up to 10 full-quality photos (25 MB each) or one video (200 MB). Photos and videos go from the
  browser straight to R2 (`/api/feed/video-upload` presign, then `media_keys` on the post). Normal members keep the old small limits.
- **Past Questions (`/questions`)**: admins upload screenshots, PDF, Word (.docx) or screen recordings (`app/questions.py`, table `past_questions`,
  created automatically by `db.create_all()`). Everyone can search and view; hidden items are visible to admins only.
- Both need the four `R2_*` variables in Vercel **and CORS on the R2 bucket** (allow `PUT` from the site origin with any header).
- **Typed text from files (Past Questions):** when an admin uploads pictures, PDFs or Word files, `POST /api/questions/read-text` types out their text
  (pictures: OpenAI `gpt-4o` vision with `OPENAI_API_KEY`, long screenshots are read in overlapping slices; PDF: `pypdf`; Word: `python-docx`).
  The admin can correct the text before saving. It is stored inside each file's JSON (`files[].text`), shown under the picture, and searchable.

