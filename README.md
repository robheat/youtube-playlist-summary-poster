# YouTube Playlist Summary Poster

Watches two YouTube playlists, generates a full article (title, summary,
body, category, tags) for each new video with an LLM (Google Gemini, or
your own Venice AI key), and publishes it -- with the video embedded --
directly into the corresponding site's own GitHub repo. Runs on a
schedule via GitHub Actions.

## How it works

- **Two target sites, one dedicated playlist each**, configured in
  `app/config.py`'s `SITE_PROFILES`:
  - `cryptocatalyst-news` (playlist `PLLuz1PRurl7k`)
  - `ainformed-dev` (playlist `PLTVCsU2gFTts`)
- **Gemini path**: the video's YouTube URL is passed directly to the
  Gemini API, which watches/understands the video itself. No transcript
  fetch is involved. Requires the video to be public.
- **Venice path**: a transcript is fetched via `youtube-transcript-api`
  and sent as plain text to Venice's chat completions endpoint.
- Either way, the model is asked to return a JSON article (title,
  summary, body, category constrained to the target site's own category
  list, tags) -- see `app/summarize/article_json.py`.
- **Publishing is a direct git push into the site's own repo**, not an
  API call -- neither site has one. Both `cryptocatalyst-news` and
  `ainformed-dev` are Next.js sites on Vercel whose content is just JSON
  files at `content/articles/<slug>.json` plus an image at
  `public/images/articles/<slug>.jpg`; Vercel deploys automatically on
  push. `app/publish/site_publisher.py` shallow-clones the target repo,
  writes those two files, and pushes -- retrying with a fetch+rebase if
  the push races the site's own daily content pipeline.
- Every run fetches the full playlist, skips videos already recorded in
  that site's `data/processed_videos_<target_site>.json`, and processes
  up to `MAX_VIDEOS_PER_RUN` of the rest. **Do not** delete these files or
  add them to `.gitignore` -- they're the only durable record of what's
  already been posted, since GitHub Actions runners are ephemeral.
- A video that fails to generate or publish is logged and retried next
  run; it never blocks the rest of the batch.
- The workflow runs both sites as a 2-entry GitHub Actions matrix
  (`TARGET_SITE=cryptocatalyst-news` / `TARGET_SITE=ainformed-dev`),
  serialized (`max-parallel: 1`) so they don't race each other committing
  back to this repo's own state files.

## Setup

### 1. Get your API keys

- **YouTube Data API key**: [Google Cloud Console](https://console.cloud.google.com/) → enable "YouTube Data API v3" → create an API key.
- **Gemini API key** (if using the Gemini provider): [Google AI Studio](https://aistudio.google.com/).
- **Venice API key** (if using the Venice provider): your Venice AI account, plus a model name -- `VENICE_MODEL` defaults to `mistral-small-3-2-24b-instruct` (matching `cryptocatalyst-news`/`ainformed-dev`'s own pipeline default) but can be overridden.
- **`SITE_REPO_PAT`**: see "Creating SITE_REPO_PAT" below.

### 2. Run locally first

```
python -m venv .venv
.venv/Scripts/activate        # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env           # then fill in your values, including TARGET_SITE
python -m app.main --dry-run
```

`--dry-run` fetches real videos and generates real articles but never
clones/pushes to the site repo or writes the state file -- safe to run
repeatedly while testing, and doesn't require `SITE_REPO_PAT` at all.

Run the test suite (all mocked except `app/publish/git_ops.py`'s tests,
which run against a real local throwaway git repo -- no live API calls
either way, no credentials needed):

```
pytest -q
```

### 3. Creating `SITE_REPO_PAT`

Fine-grained PAT, scoped to exactly `cryptocatalyst-news` and
`ainformed-dev`, **Contents: Read and write** only. Do not reuse either
site repo's existing `PAT_TOKEN` secret -- that already serves an
unrelated purpose in `ainformed-dev/bookmark-pipeline.yml`.

1. Go to <https://github.com/settings/personal-access-tokens/new> (resource owner: your account).
2. Repository access → "Only select repositories" → select `cryptocatalyst-news` and `ainformed-dev`.
3. Permissions → Repository permissions → **Contents: Read and write**. Leave everything else at "No access."
4. Generate, copy the token immediately (shown once).
5. Set a calendar reminder to rotate it before it expires.

### 4. Push to GitHub and configure secrets/variables

Under **Settings → Secrets and variables → Actions** on this repo, add:

| Name | Type | Required | Notes |
|---|---|---|---|
| `YOUTUBE_API_KEY` | Secret | always | |
| `SUMMARY_PROVIDER` | Variable | always | `gemini` or `venice` |
| `GEMINI_API_KEY` | Secret | if provider=gemini | |
| `GEMINI_MODEL` | Variable | optional | defaults to `gemini-2.5-flash` |
| `VENICE_AI_API_KEY` | Secret | if provider=venice | |
| `VENICE_MODEL` | Variable | optional | defaults to `mistral-small-3-2-24b-instruct` |
| `WEBSHARE_PROXY_USERNAME` / `PASSWORD` | Secret | optional | see "Transcript IP blocking" below |
| `SITE_REPO_PAT` | Secret | always unless `--dry-run` | see above |
| `MAX_VIDEOS_PER_RUN` | Variable | optional | defaults to `5` |

(`TARGET_SITE` is set automatically per matrix leg -- you don't configure it as a secret/variable.)

### 5. Add the site-side code (one-time, per site repo)

Both `cryptocatalyst-news` and `ainformed-dev` need a small code change so
an embedded YouTube player actually renders (their article body renderers
deliberately don't support raw HTML/iframes): an optional
`youtubeVideoId` field on the `Article` type, a `YouTubeEmbed` component,
and one line in each repo's `app/articles/[slug]/page.tsx` to render it
when present. This only needs doing once and is independent of this
repo's own deploys.

### 6. Test the workflow

Go to **Actions → Process YouTube Playlists → Run workflow**, tick
`dry_run`, and run it (this runs both matrix legs). Check the logs. Once
that looks right, run it again with `dry_run` unticked against a small
test playlist swapped into `SITE_PROFILES` temporarily, and confirm a
real commit lands in the target site repo and Vercel deploys it
correctly. Then point `SITE_PROFILES` back at the real playlists.

The schedule defaults to daily (`0 13 * * *` UTC) -- edit the `cron:`
line in
[`.github/workflows/process-playlist.yml`](.github/workflows/process-playlist.yml)
to match how often you add videos.

## Transcript IP blocking (Venice path only)

YouTube blocks known cloud/datacenter IP ranges -- including GitHub
Actions runners -- from fetching transcripts, sometimes immediately. If
`app/summarize/venice.py` starts failing with `TranscriptError`
mentioning `IpBlocked` or `RequestBlocked`, sign up for a
[Webshare](https://www.webshare.io/) rotating-residential proxy plan and
set `WEBSHARE_PROXY_USERNAME`/`WEBSHARE_PROXY_PASSWORD`. This only
affects the Venice path -- Gemini ingests the YouTube URL directly and
never fetches a transcript.

## Permanently-skipping a video

If a specific video will never succeed and you don't want it retried
forever, hand-edit the relevant `data/processed_videos_<target_site>.json`
and add an entry for it:

```json
"VIDEO_ID": { "title": "...", "status": "skipped_manual", "processed_at": "..." }
```

Any entry present in the file is treated as done, regardless of its
`status` value.

## Adding a third site

Add a new `SiteProfile` entry to `SITE_PROFILES` in `app/config.py`
(repo owner/name, playlist ID, category taxonomy), add it to the
`matrix.target_site` list in
[`.github/workflows/process-playlist.yml`](.github/workflows/process-playlist.yml),
and do the same site-side `youtubeVideoId`/`YouTubeEmbed` change in that
repo. No other code changes needed.
