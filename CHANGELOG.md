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
  once Gemma has finished what it was doing.

### Changed

- **Generation time budgets follow Gemma's measured speed.** A short calibration
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
  networks) the app could fail to start and Gemma looked offline: local calls to the
  app's own server and to Ollama no longer go through the proxy.
- Windows: every call to Ollama waited about 2 s (`localhost` tried IPv6 first, which
  Ollama does not listen on).

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
- **Embodied assistant "Gemma"**: an animated bubble over the page with idle, reading,
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
