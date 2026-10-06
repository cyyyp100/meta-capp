# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- MIT license, contribution guide, code of conduct, security policy, issue and pull
  request templates.
- **Runs on every desktop OS, with or without a GPU.** Release archives for Apple
  Silicon macOS, Intel macOS, Windows and Linux x86_64, each smoke-tested.
- **Browser mode**: when no native web engine is usable (Linux without GTK or Qt,
  Windows without WebView2, no display) the app opens in the default browser,
  behind the same guards. `--browser` (or `METACAPP_BROWSER=1`) forces it.
  Importing a document in that mode uploads a copy into the data folder
  (`POST /api/library/upload`); deleting the document deletes the copy.
- Launching the app while it already runs — or is still starting, after an impatient
  double-click — reopens the running instance.
- Browser mode can be quit without a terminal: **Quit Meta-Capp** in the profile menu,
  or close the tab — the app stops by itself three minutes after the last tab closes,
  once Clikoda has finished what it was doing.
- **Locate a moved file.** A document whose file was moved, renamed or deleted says
  so on its card, on the resume card and in the reader, with a **Locate…** button:
  pick the file where it is now and the same document comes back — progress,
  highlights, sessions, folder and title included. Other missing documents moved
  along with it are found at the same time. A file whose content changed since the
  import is only linked after confirmation.
- **Clikoda reads the pace of the quick review.** The time spent on each card's
  question and answer, and on the whole review, is measured before reading starts.
  Clicking through faster than the text can be read lowers attention and
  metacognition; lingering, especially on the answer, lowers retention; a very long
  stop on one side lowers attention. The end-of-session debrief comments on it.
- **The entry airlock's length is a setting** (Settings ▸ Reading): 30 s to 5 min,
  1 min by default.

### Changed

- **The entry airlock waits for you.** When its countdown ends it no longer moves
  on to the cards by itself (before a PDF or a language session): you continue
  when you are ready.
- **The quick review can no longer be skipped.** The *Start now* button under the
  cards is gone; the review ends after its last card.

- **The assistant is now called Clikoda.** It still runs on Google's open-source
  Gemma 4 model (`gemma4:e4b`) through Ollama; only its name changes. The floating
  panel's saved position and layout reset once.
- **Generation time budgets follow Clikoda's measured speed.** A short calibration
  call at startup and every answer feed an estimate of the machine's throughput;
  a machine slower than the reference (CPU-only laptop, Intel Mac) gets
  proportionally longer budgets, up to 8×, instead of timing out on every long
  answer. A faster machine keeps the reference budgets.
- When Ollama cannot load the model for lack of memory, the reader says so in
  plain words instead of answering with a generic fallback, and the call is no
  longer retried.

### Fixed

- Windows from source: the frontend auto-build failed (`npm` is `npm.cmd`), and
  the conda re-exec looked for `bin/python`.
- Behind an HTTP proxy (system setting or `http_proxy`, common on school and company
  networks) the app could fail to start and Clikoda looked offline: local calls to the
  app's own server and to Ollama no longer go through the proxy.
- Windows: every call to Ollama waited about 2 s (`localhost` tried IPv6 first, which
  Ollama does not listen on).
- A document whose file had moved no longer breaks the app: its thumbnail answered
  with a server error (500) and an error trace in the log, and the reader opened a
  session on broken pages and lost its connection to Clikoda at the first
  rephrasing. The reader now offers to locate the file instead.
- Re-importing a file that was moved since its import reopens its document instead
  of creating a blank duplicate.
- **Quiz debrief.** The analysis now speaks about the session you set up (subject,
  keywords, or multi-learning) instead of your whole profile. *Courses to reinforce*
  only lists documents from your library where you missed questions; questions from
  the built-in catalogue no longer turn into courses that do not exist. A **Back**
  button next to **Restart** returns to a blank quiz setup, and **Next** shows a
  single arrow.

### Security

- The local API refuses requests that the browser itself marks as coming from another
  site or another local port (`Sec-Fetch-Site`). In browser mode, every port of
  127.0.0.1 counts as the same site and received the launch cookie.
- Release builds pin PyInstaller and its community hooks (`requirements-build.txt`,
  audited by `pip-audit`): a release no longer depends on whatever version PyPI
  serves that day.

## [0.1.0] — Initial public release

### Added

- **Free-scroll PDF reader**: the document is rendered page by page at full fidelity,
  with no reconstruction and no progression locks.
- **Embodied assistant "Clikoda"**: an animated bubble over the page with idle, reading,
  thinking, answering, intervention and sleeping states.
- **Submit-time context capture**: every question is answered against a snapshot of the
  page visible at the moment Send was pressed.
- **Autonomous interventions**: LLM-decided help offers, pedagogical questions, pause
  suggestions and page rephrasings, gated by per-mode dwell and cooldown policy
  (`discret` / `normal` / `coach`).
- **Metacognitive engine**: six hidden gauges (attention, comprehension, curiosity,
  retention, creativity, metacognition) feeding a long-term profile with an adaptive
  blending factor.
- **Adaptive questioning pipeline**: question → answer → evaluation → feedback →
  flashcard, non-blocking.
- **Session flow**: concentration airlock with an AI-generated curiosity hook, flash
  review of due flashcards, free reading, end-of-session synthesis and reflection.
- **Source-code reading**: imported source files are paginated into readable code blocks.
- **Bilingual FR/EN** interface, with the LLM prompt language following the UI choice.
- **Fully local inference** via Ollama (`gemma4:e4b`), with graceful degradation when
  the model is unavailable.
- Desktop shell (`pywebview` + FastAPI + React/Vite), versioned SQLite schema with
  incremental migrations, PyInstaller packaging for macOS and Windows, and CI covering
  tests, lint, frontend build and security scans.

[Unreleased]: https://github.com/cyyyp100/meta-capp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cyyyp100/meta-capp/releases/tag/v0.1.0
