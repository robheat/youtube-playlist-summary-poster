# YouTube Playlist Summary Poster

Watches a YouTube playlist, summarizes each new video with an LLM (Google
Gemini, or your own Venice AI key), and publishes the video (embedded) +
summary to your website via its API. Runs on a schedule via GitHub
Actions.

## How it works

- **Gemini path**: the video's YouTube URL is passed directly to the
  Gemini API, which watches/understands the video itself. No transcript
  fetch is involved. Requires the video to be public.
- **Venice path**: a transcript is fetched via `youtube-transcript-api`
  and sent as plain text to Venice's chat completions endpoint.
- Every run fetches the full playlist, skips videos already recorded in
  [`data/processed_videos.json`](data/processed_videos.json), processes up
  to `MAX_VIDEOS_PER_RUN` of the rest, and commits the updated state file
  back to the repo. GitHub Actions runners are ephemeral, so this file is
  the only durable record of what's already been posted -- **do not**
  delete it or add it to `.gitignore`.
- A video that fails to summarize or publish is logged and retried on the
  next run; it never blocks the rest of the batch.

## Setup

### 1. Get your API keys

- **YouTube Data API key**: [Google Cloud Console](https://console.cloud.google.com/) → enable "YouTube Data API v3" → create an API key.
- **Gemini API key** (if using the Gemini provider): [Google AI Studio](https://aistudio.google.com/).
- **Venice API key** (if using the Venice provider): your Venice AI account. Also note a model name from your account's available models -- there's no safe default, `VENICE_MODEL` must be set explicitly.
- **Your website's API URL + key**: whatever your existing site uses to accept new content. See "Adjusting the website payload" below -- this app makes a best guess at the request shape and you'll likely need to tweak it.

### 2. Run locally first

```
python -m venv .venv
.venv/Scripts/activate        # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env           # then fill in your values
python -m app.main --dry-run
```

`--dry-run` fetches real videos and generates real summaries but never
calls your website or writes `data/processed_videos.json` -- safe to
run repeatedly while you're testing. Point `PLAYLIST_ID` at a small test
playlist (1-2 videos) first.

Run the test suite (all mocked, no live API calls, no credentials
needed):

```
pytest -q
```

### 3. Push to GitHub and configure secrets/variables

Create a GitHub repo, push this project to it, then under **Settings →
Secrets and variables → Actions**, add:

| Name | Type | Required | Notes |
|---|---|---|---|
| `YOUTUBE_API_KEY` | Secret | always | |
| `PLAYLIST_ID` | Variable | always | |
| `SUMMARY_PROVIDER` | Variable | always | `gemini` or `venice` |
| `GEMINI_API_KEY` | Secret | if provider=gemini | |
| `GEMINI_MODEL` | Variable | optional | defaults to `gemini-2.5-flash` |
| `VENICE_API_KEY` | Secret | if provider=venice | |
| `VENICE_MODEL` | Variable | if provider=venice | no safe default -- required |
| `WEBSHARE_PROXY_USERNAME` | Secret | optional | see "Transcript IP blocking" below |
| `WEBSHARE_PROXY_PASSWORD` | Secret | optional | must be set together with the username |
| `WEBSITE_API_URL` | Variable | always | |
| `WEBSITE_API_KEY` | Secret | always | |
| `MAX_VIDEOS_PER_RUN` | Variable | optional | defaults to `5` |

("Variable" = repo Variables tab, plaintext, fine for non-secret config.
"Secret" = repo Secrets tab, encrypted.)

### 4. Test the workflow

Go to **Actions → Process YouTube Playlist → Run workflow**, tick
`dry_run`, and run it. Check the logs. Once that looks right, run it
again with `dry_run` unticked against your test playlist, and confirm a
post actually shows up correctly on your website. Then point
`PLAYLIST_ID` at your real playlist.

The schedule defaults to daily (`0 13 * * *` UTC) -- edit the `cron:`
line in
[`.github/workflows/process-playlist.yml`](.github/workflows/process-playlist.yml)
to match how often you add videos.

## Adjusting the website payload

`app/publisher.py`'s `build_payload()` is a best guess at what your
website's API expects:

```python
{
    "video_id": ..., "title": ..., "url": ..., "embed_url": ...,
    "channel_title": ..., "thumbnail_url": ..., "published_at": ...,
    "summary": ...,
}
```

sent as a JSON POST to `WEBSITE_API_URL` with an `Authorization: Bearer
WEBSITE_API_KEY` header. Edit `build_payload()` (and, if your site uses a
different auth scheme, `publish_video()`) to match your actual API once
you have its real contract.

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

If a specific video will never succeed (e.g. captions permanently
disabled, and you don't want to keep retrying it), hand-edit
`data/processed_videos.json` and add an entry for it:

```json
"VIDEO_ID": { "title": "...", "status": "skipped_manual", "processed_at": "..." }
```

Any entry present in the file is treated as done, regardless of its
`status` value.
