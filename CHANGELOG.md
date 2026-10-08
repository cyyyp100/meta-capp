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
- **Language sessions open with the entry airlock again** — the same one as before
  a PDF, whose length follows the same setting — followed by a quick review of at
  most five flashcards of the language you are studying: due ones first, then the
  most recent. Those cards count toward the session's card limit
  and are not served again later in the session. Your first visit to a language
  (introduction and placement test) has no airlock.
- **Quizzes and language sessions move your gauges.** Like a reading session, each
  quiz and each language session now draws its own gauge curve: quiz answers (with
  their response time), language games, second-wave self-ratings, "understood?"
  answers and graded lesson exercises are its measures. Your profile then moves
  toward that curve, by as much as was actually measured: a right or wrong answer
  only informs attention, comprehension and retention, and a skill measured once
  weighs less than one measured ten times. A quiz weighs half as much as a reading
  or a language session: it checks what you learned rather than teaching it.
- **My progress has three categories: Reading, Quiz and Languages**, each session
  with what is specific to it — the answers you gave in a quiz, with Clikoda's
  debrief and the courses to reinforce; the episode, the point of the day and the
  words you gained in a language (still no score); where you slowed down in a
  reading — and all of them with the gauge curve and what it moved in your profile.
  The weekly recap counts every kind of session.
- **"Episode ready", on every page.** When Clikoda finishes writing a language
  episode, a small message in the bottom-right corner says which one and in which
  language ("Spanish: episode 3 is ready"), whatever page you are on; *Open* takes
  you to that language. On the Languages page, a language whose next episode is
  written and not played yet shows *Pending* in the corner of its card.

### Changed

- **Three days off before a mandatory re-read, and the ready episode is kept.** Up
  to three days without a session in a language (two before), the next session
  plays the episode that is ready. Beyond that, the session is a re-read with no new
  episode — a short session asked for included — and the episode already written
  waits for the next session, the same day included: it is no longer thrown away
  and rewritten after a week off. The language's home says so (*Re-read before
  episode 3*).
- **"Pages read" counts pages you actually read**: at least 5 seconds on a page,
  visits added up, pauses left out. Flipping through twenty pages to find one reads
  one, and the time spent in the entry airlock is no longer a reading of page 1.
  *Where you slowed down* only lists pages read.
- **The entry airlock reviews the document's subject first.** Its cards come from
  the subject of the document you are opening — for a Turkish course, the Turkish
  cards of the language module — due cards first, then completed with your other
  subjects, never with another language.
- **No more automatic flashcards that need the document.** Clikoda only proposes a
  card that can be understood and answered without the document; cards saying
  "according to the text", "based on Table 3.5"… are refused, and those created
  before are removed by the update (cards you created yourself are kept). Questions
  about a figure or linking to another passage no longer make cards.
- **The entry airlock waits for you.** When its countdown ends it no longer moves
  on to the cards by itself (before a PDF or a language session): you continue
  when you are ready.
- **The quick review can no longer be skipped.** The *Start now* button under the
  cards is gone; the review ends after its last card.
- **Every language flashcard shows how its word is pronounced**, on the side written
  in the language you are learning. Spanish, English and German now get one too:
  Clikoda writes it in the International Phonetic Alphabet when it glosses an
  episode (Mandarin pinyin and Arabic transliteration are still computed). A word
  without a pronunciation waits for one before becoming a card.

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
- **One subject per language.** The single "Languages" subject is gone: English,
  Spanish, German, Mandarin… are each a subject of their own, with the language
  module's flag and CEFR level on the profile. A language becomes one of your
  subjects after your first session in it — opening it in Languages is not enough.
  A course meant to learn a language is filed under that language when imported; a
  document merely written in a language keeps the subject of its content. Your
  "Languages" mastery, which came from the built-in English vocabulary questions,
  is now English.
- **Your subjects are your own, and the quiz offers exactly them.** The profile and
  the quiz's subject picker show the same list: the subjects of the documents in
  your library (Clikoda files each one when it is imported), the languages you have
  practised, and any subject you have already been measured in. A subject without
  a playable question yet is shown greyed out. The built-in question catalogue now
  only rounds out these subjects: it no longer adds History or Geography to every
  profile, so a fresh install has no quiz until a document is imported and read.
  A subject whose last document was deleted, and in which nothing was measured,
  leaves the profile.

### Fixed

- Formulas in flashcards are rendered wherever a card is shown (entry airlock,
  Flashcards page, weekly recap, language sessions, brainstorming sources).
  `$$…$$`, `\(…\)` and `\[…\]` are recognized, and two amounts such as "5$ and 10$"
  no longer turn into a formula.
- A language episode interrupted by closing the app, or that failed to be written,
  is written again at the next start and when its language's home opens, instead of
  waiting for a session — never while Ollama is off.
- On a language's home, *Short session* and *Library* look disabled when they are and
  say why; opening an episode from the library says it is loading, or that it could
  not be opened.
- Reflections written at the end of a language lesson, and the feeling picked at the
  end of an episode, were silently dropped; they are now kept with their session.
- Languages studied with episodes never appeared on the profile: only lessons of
  the older flow were counted.
- Subjects were shown untranslated: the profile always in French, the library cards
  and the quiz results under their raw key. The demo document no longer creates a
  subject of its own ("Computer science" next to "informatique").
- A quiz no longer moves your retention twice (once per answer, then again at the
  end): it moves your profile once, when the quiz ends — or when you leave it.
- In My progress, "N criteria moved" only counts criteria that actually moved.
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
