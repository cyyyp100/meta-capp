# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Settings ▸ Help ▸ About shows the third-party licenses.** The notices
  shipped in every build (`THIRD_PARTY_NOTICES.txt`) open in a window of the
  app, next to a link to the privacy policy, now versioned as `PRIVACY.md`.
- **Clikoda says she is an AI.** Her first message in the reader, the guided
  tour and the About card state that she is a local language model and can be
  wrong (EU AI Act, article 50).

## [0.2.3] — 2026-10-23

### Changed

- **Clikoda has a face: the sperm whale of the new logo.** In the reader, the
  closed bubble is now the whale itself, in the app's orange and without a
  background, instead of a sphere with two eyes. She faces the document,
  floats and blinks now and then (twice per cycle, once a double blink, at
  uneven moments). While she inspects the page she sends three clicks at it,
  without blinking. When the discussion is open and she is thinking, the
  outline of her head draws itself and her three clicks go out one after the
  other in front of her jaw (a *coda*, a sperm whale's call), in place of the
  three bouncing dots. The panel header shows her head instead of a sparkle.
  With *reduce motion* set in the system, all of this stays still.

### Added

- **The application has its own icon.** The macOS bundle and the Windows
  executable used PyInstaller's default icon. They now carry Clikoda's tile
  (`desktop/icons/meta-capp.icns` and `.ico`, with a simplified silhouette for
  16–32 px). The browser tab shows it too (`favicon.ico`, `favicon.svg`), and so
  does the sidebar, next to the name. `scripts/build_icons.py` rebuilds every
  size from the two 1024 px renders in `desktop/icons/source/`, next to the
  vector drawing and its generator.

## [0.2.2] — 2026-10-23

### Fixed

- **Clikoda's automatic questions no longer stop during a reading.** Several
  paths could silence her for the rest of a session without any visible error:
  a failure while preparing a question left it counted as "in progress" forever,
  an error in the reader's background loop stopped it for good, an error while
  handling one message closed the connection, and a free answer counted twice,
  so Clikoda could look idle while a question was still being prepared. Every
  request from the reader now goes through a single path that always settles
  it, and failures are logged instead of silencing Clikoda.
- **Sessions resumed at startup no longer get in the way of reading.** Their
  summaries ran ahead of every question in the reader, started before the speed
  calibration (on a model the calibration then set aside), and closing the reader
  cut them off. They now run as background work, after the calibration and after
  anything a screen is waiting for.
- **Every task in Clikoda's queue ends with exactly one callback**, even when its
  caller has given up or an error occurs outside the generation itself; a
  callback can no longer wait on another task (it used to freeze the queue until
  the timeout).
- **"Why does Meta-Capp work this way?" no longer talks about a web port of a
  Tkinter app.** The introduction, the session flow and the description of the
  software now describe the app as it works today.

## [0.2.1] — 2026-10-21

### Fixed

- **Sticky notes can be placed anywhere on the page.** Clicking a blank area
  (margins, between lines) after "Place a sticky note" did nothing: on release, the
  text layer's end-of-content block was re-inserted into the page even when already
  in place, and the browser dropped the click (WebKit and Chromium alike). Only a
  click right on a word placed the note.
- **Error-spotting questions come up half as often.** The question picker made them
  the favourite type whenever attention was low: 13 % of draws then, 5.5 % now
  (3.5 % otherwise, down from 6.7 %).
- **Clikoda no longer goes quiet after a number of interventions.** The local
  edition has no intervention cap; cooldowns, the warm-up and the per-page
  anti-repetition set the pace.
- **Attention follows what you actually do while reading.** It stayed low in every
  session, whatever the learner did:
  - a session now starts from the profile moved towards neutral
    (`50 + (profile − 50) × 0.8`) instead of 80 % of it, which pulled every measured
    gauge down session after session (attention profile 36 → 23 over eight readings);
  - a written answer no longer costs attention for the time it took (up to 6 points
    per answer past 12 s — 42 points in a session); the passive drift already
    observes that time;
  - asking Clikoda a question, answering one, highlighting and writing a note credit
    attention (at most once per 20 s per gesture), and so does any pause you resume
    after, not only the ones Clikoda suggested;
  - the warm-up flashcards cost at most 5 attention points (up to 15 before).
- **Curiosity no longer hits 100 in every session.** Each question asked added
  12.8 points; it now weighs half as much, and curiosity rises more slowly as it
  nears 100.
- **A reading session left open by closing the app is closed on the next start**,
  instead of staying "Session in progress" forever in "My progress": closed at its
  last trace (the reader now records the reading time every minute), then finalized
  as if the exit reflection had been skipped, with Clikoda's end-of-session analysis,
  which is now kept and shown in the session's detail. A session where nothing was
  read is removed, as when leaving from the entry airlock. The study day counted is
  the session's own. Schema v46 (`reading_sessions.analysis`,
  `reading_sessions.finalized_at`); sessions already closed are left as they are.

## [0.2.0] — 2026-10-21

### Added

- **Clikoda's model is a setting** (`Settings ▸ Clikoda`). The gemma4 family is declared
  in one table (`nwol/config/settings.py:LLM_MODELS`) with what each model downloads, the
  RAM it needs and the speed it writes at. "Automatic" (the default) picks the most capable
  model installed that this machine can actually load **and that stays fluent on it**:
  the startup calibration measures each model it runs, and one that writes below
  15 tokens/s is set aside for the next best one — on a 16 GB Apple M4, `gemma4:12b`
  (11.9 tokens/s) gives way to `gemma4:e4b` (29.7), which RAM alone could not tell apart.
  The verdict holds 14 days for this machine's RAM, a later measure above the threshold
  lifts it, the tiny model is never picked for speed alone, and Settings names the model
  set aside with its measured speed. An explicit choice is always honoured — even one that
  is missing, too heavy or too slow, because nothing is disabled and the reason is stated
  instead.
- **`GET /api/llm/status`**: whether Ollama answers, which model runs, whether it fits in
  this machine, the measured speed, and the `ollama pull` command to copy when something is
  missing. The reader's status light now tells "connected" apart from "Clikoda can answer"
  (green / amber / grey) — it used to stay green with Ollama switched off.

- **A tiny tier for 4 GB machines**: `qwen3:1.7b` (1.4 GB) joins the model table — no
  gemma4 variant fits in 4 GB. "Automatic" picks it only when nothing bigger fits.
- **Economy mode** (`Settings ▸ Clikoda`, Automatic / On / Off; automatic with the tiny
  model or below 8 GB of RAM): one context for every task (Ollama no longer reloads the
  model between requests), compact prompts that fit in it, budgets that stretch down to
  ~0.9 token/s but never past a quarter of an hour per answer, the model unloaded after
  five idle minutes, and no background work, autonomous help or embeddings.
- **The reader announces slow answers**: on a slow machine or in economy mode, "answer
  within N min at most" (the server's total budget, republished when the task leaves the
  queue) and a **Cancel** button.
- A dismissible note on the language home page for the tiny model, separate from the
  general one; the home page says when economy mode keeps episodes from being written.
- **Search the document** (⌘F on macOS, Ctrl+F elsewhere, or the toolbar's magnifier):
  accents and capitals are ignored, a word hyphenated at the end of a line is found
  whole, and "3 / 17" walks through every occurrence of the document (Enter /
  Shift+Enter, ⌘/Ctrl+G, F3; Esc closes). Code files are searched too. A scanned PDF
  says it has no text to search; an occurrence below a blocking question is counted but
  not reached, and one inside a free-recall passage stays hidden. The document is
  indexed once, in batches that leave the PDF engine free for the pages being read
  (`GET /api/library/doc/{id}/find`, `…/page/{n}/find`).
- **A bookmark to resume reading**, at the top right of every page: one per
  document, set, moved or removed in a click. The reader opens on the bookmarked
  page, the entry airlock's curiosity hook is about that page, the "Resume" card
  names it and the time left counts from it. Without a bookmark the reader opens
  on page 1, as before. Schema v44 (`documents.bookmark_page`); no existing
  position is turned into a bookmark (`POST /api/library/doc/{id}/bookmark`).
- **Note-taking in the reader.** A selection is highlighted with a **label**
  (Important, Definition, Example, To review, Question, Idea, then your own: ten
  colors, rename, recolor, reorder, delete) in one of four **styles** (highlighted,
  underlined, struck through, boxed), and takes a **note** — "Note" in the selection
  bar opens it directly; formulas `$…$` render in the hover card. **Sticky notes** are
  placed anywhere on a page (in the margin of a code file), and **page markers** mark
  the pages that matter, one per page. The **notebook** (toolbar, left drawer) lists the
  bookmark, the page markers and everything noted, page by page, with filters (labels,
  types, "with a note") and an accent-insensitive search; a click brings the reader to
  the item, which blinks, and items are edited in place. **Export (.md)** saves the
  notebook as Markdown, **Copy as Markdown** puts it on the clipboard. Schema v45
  (`annotation_labels`, `reader_notes`, and label, style, note on `reader_highlights`):
  existing highlights get the label of their former color
  (`GET /api/library/doc/{id}/annotations`, `…/annotations.md`, `/api/annotations/labels`).

### Changed

- **Clicking a highlight opens it for editing** (label, style, note, add to Clikoda's
  context, delete) instead of deleting it. A text selection can no longer start on a
  highlighted passage; "Add to Clikoda's context" makes up for it.

- **The "Resume" card shows the time left in the document** ("≈ 2 h 10 to finish"), at
  the reader's measured pace: the median time per page read in this document, else in
  documents of the same kind (a code file does not borrow the pace of PDFs), else 2 min a
  page, labelled as an estimate. It used to show the median of the last 40 sessions,
  quizzes and language sessions included (7 min for someone reading in 22-minute
  stretches), whatever the document. The card now resumes the document of the last
  session that actually read something, so a PDF imported but never opened no longer
  takes its place (`GET /api/library/resume`).
- Prompt sizes are estimated **per tokenizer** (five character classes, calibrated on 60
  measured prompts): vocalized Arabic costs 0.6 token per character with Gemma and 0.8
  with qwen3, not 0.5, and digits cost one each. The budget benches now run for every
  model of the table, in normal and economy mode; a new bench covers the reader's
  prompts in a compact context. Episode content tasks get a 5120-token window (Gemma),
  and the Arabic episode length cap is 180 words with qwen3's tokenizer.
- In a compact context (economy mode, or the tiny model) the question uses a compact
  prompt (only the type already chosen, ~4× shorter), and the visible page, the answer
  being evaluated and the passages found elsewhere are bounded in estimated tokens.
- A model that cannot see images never receives the page image, and no prompt claims
  one is attached.
- The out-of-memory message names the active model and the RAM it needs (it said
  "about 16 GB" for every model).
- `gemma4:12b`'s reference speeds are the ones measured on the 16 GB Apple M4 (11 tokens/s
  written, 85 read, pessimistic like the other rows): its time budgets are longer, and
  choosing it explicitly no longer announces a "slow machine" — the model is slow, not
  the machine.
- Time budgets follow the chosen model. The cost of a heavier model and the measured
  slowness of the machine are two separate factors, so `OLLAMA_MAX_SLOWDOWN` again bounds
  only the machine; measured throughput is kept per model. Each task's `num_ctx` is capped
  by what the active model holds, in a single place.
- A language episode, a point lesson and a written correction record the model that
  actually wrote them, rather than a constant.

### Fixed

- In the native window, **Settings ▸ Data ▸ Export** did nothing: pywebview ignores
  download links unless told otherwise. The shell now allows them, and the system's save
  panel opens (the notebook's Markdown export goes through it too).
- Deleting a highlight with an id from another document deleted it anyway: the route
  ignored the document. It is now scoped to the document, like every new route.
- A passage highlighted or added to Clikoda's context from a PDF was saved without
  spaces ("inatypicaltrainingscript…"): the reader's text layer is one element per
  word, and the browser read them glued together. The quote is now rebuilt from
  the selected words, with spaces, and a word hyphenated at the end of a line is
  joined back. Quotes saved before keep their old text.
- The guided tour promised that a document reopens where you stopped; the reader
  always opened on page 1. The tour now describes the bookmark, which does.
- A word hyphenated at the end of a line ("differen- / tials") was one word for the
  reader's text layer, with a box covering both lines: selecting it lit up a rectangle
  as tall as the paragraph. It is now two words, each on its line.
- Leaving the reader from the entry airlock no longer records the warm-up as time spent
  reading page 1, nor moves the last page seen back to 1. That session is erased anyway;
  its time skewed the measured reading pace.
- The curiosity hook could read "Entre dans **non renseigné** en cherchant…". An empty
  field wrote a placeholder into the prompt, and the offline fallback re-read its own
  prompt and found it. Empty context lines are now omitted, the fallback receives the
  context directly, and its sentences follow the interface language (they were hard-coded
  French).

## [0.1.0] — 2026-10-12 — Public beta

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
  (introduction and placement test) has no airlock. Neither does a re-read imposed
  by more than three days away, at the start or at the end: you come back, re-read
  and review your flashcards — all those due, up to the limit, inside the session —
  then return straight to the Languages page, with no farewell, end screen or rest
  minute. Only the offer to step back a few episodes, after a failed check, remains.
- **A curiosity hook before each language episode.** As before a PDF, a language
  session's entry airlock shows a sentence from Clikoda, here about the episode you
  are about to discover: a situation, a character, a question it raises, never how
  it ends. It is written while the airlock runs, in the language Clikoda explains
  in. A session that plays no new episode (a re-read, a comeback after a few days,
  the weekly review) has none, and neither does one while Clikoda is off.
- **Quizzes and language sessions move your gauges.** Like a reading session, each
  quiz and each language session now draws its own gauge curve: quiz answers (with
  their response time), language games, second-wave self-ratings, "understood?"
  answers and graded lesson exercises are its measures. Your profile then moves
  toward that curve, by as much as was actually measured: a right or wrong answer
  only informs attention, comprehension and retention, and a skill measured once
  weighs less than one measured ten times. A quiz weighs half as much as a reading
  or a language session: it checks what you learned rather than teaching it.
- **In a language session, attention only drops when you drift off.** A wrong or
  slow answer, or a run of mistakes, no longer costs attention. It drops only when
  you turn a page, or go from one question to the next on the same page, well after
  the expected time — and only for the part of that time spent without a gesture:
  moving the mouse along the text, scrolling to keep the line at eye level, typing
  and clicking all count. A long interruption is one drop, never a free fall. The
  same gestures keep a session's time active: reading by following the text with the
  mouse no longer counts as silence.
- **My progress has three categories: Reading, Quiz and Languages**, each session
  with what is specific to it — the answers you gave in a quiz, with Clikoda's
  debrief and the courses to reinforce; the episode, the point of the day and the
  words you gained in a language (still no score); where you slowed down in a
  reading — and all of them with the gauge curve and what it moved in your profile.
  The weekly recap counts every kind of session.
- **"Episode ready", on every page.** When Clikoda finishes writing a language
  episode, a small message in the bottom-right corner says which one and in which
  language ("Spanish: episode 3 is ready"), whatever page you are on. It informs
  without taking you anywhere: no button pulls you out of what you are doing. On the
  Languages page, a language whose next episode is written and not played yet shows
  *Pending* in the corner of its card.

### Changed

- **Release builds are smaller and signable.** The macOS build no longer drags in
  OpenCV, numpy and FFmpeg from the build machine (200 MB → 85 MB), carries its
  version and copyright, and is signed by PyInstaller with the hardened runtime and a
  secure timestamp when a Developer ID is configured, then notarized and checked by
  Gatekeeper. Windows builds are signed through Azure Artifact Signing when it is
  configured. Every release embeds `THIRD_PARTY_NOTICES.txt`.
- Log lines carry their date and time, and the native file dialog follows the
  interface language.

- **Verbs are reviewed in the infinitive.** A language card shows a word's dictionary
  form — the infinitive for a verb — with the meaning of that form and its
  pronunciation, never the conjugated word met in the episode nor its translation
  there (*tener* — *avoir*, not *tener* — *Nous avons*; *be* pronounced /biː/, not
  /wəz/). The words to use in the writing step follow the same rule, and the word
  bubble adds the base form's pronunciation and meaning (*Nous avons — base form:
  tener /teˈneɾ/ = avoir*). A card made before takes the right meaning as soon as an
  episode glosses another form of the same verb, unless you edited it. Arabic cards
  still show the vocalized word of the text.
- **A language step that asks questions waits for your answers.** The games, the
  lesson's practice, the second wave, the check, the cards and the writing step keep
  **Continue** disabled, and say why, until every question has an answer — a wrong
  one counts. The writing step needs at least one word. The feeling asked at the
  goodbye stays optional: leaving it blank is itself measured.
- **Three days off before a mandatory re-read, and the ready episode is kept.** Up
  to three days without a session in a language (two before), the next session
  plays the episode that is ready. Beyond that, the session is a re-read with no new
  episode, and the episode already written waits for the next session, the same day
  included: it is no longer thrown away and rewritten after a week off. The
  language's home says so (*Re-read before episode 3*).
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

### Removed

- Code that no longer served: the adaptive language sequencer of the old flow
  (`/api/lang/session`, `/api/lang/session/complete`, `/api/lang/session-types`,
  the deprecated `/api/lang/lesson`), `/api/flashcards/due`,
  `/api/session/{id}/metrics`, about a hundred unused functions, the strings of the
  former Tkinter interface, and the interactive API documentation (`/docs`,
  `/redoc`, `/openapi.json`).
- **Short session** and **Just re-read today** are gone from a language's home.
  The session is always the one Clikoda picks: the episode that is ready, a re-read
  while the next one is being written or after a few days away, the weekly review.
  Short sessions already played stay in My progress.

### Fixed

- **Restoring a backup kept a complete safety copy of the current data.** The copy
  was made from the database file alone and could miss the latest changes — or be
  empty — since they still sat in SQLite's journal. It is now a consistent snapshot,
  only the latest one is kept, and *Erase everything* deletes it.
- The answer evaluation ran out of context when the page image was attached (the
  model then lost the beginning of its instructions), and Clikoda's intervention
  decisions could be cut mid-answer: both budgets were raised.
- The log said "Ollama refused the images" for any failed generation with an image;
  it now names the actual cause, such as the model repeating itself.
- Mode changes in the reader, the progress page's criteria and the file dialog were
  shown in French in the English interface.

- **My progress, *Where you slowed down*.** The time spent on each page of a reading
  session was overwritten, once the session had ended, by the rest pause that follows
  it: only "page 1" was left, with the length of the pause. Each page read now keeps
  its number and its time (m:ss). The rest pause no longer adds points to the
  session's gauge curves either, nor cancels the analysis being written for the
  session. Sessions already affected cannot be recovered: their time per page was
  erased.
- Formulas in flashcards are rendered wherever a card is shown (entry airlock,
  Flashcards page, weekly recap, language sessions, brainstorming sources).
  `$$…$$`, `\(…\)` and `\[…\]` are recognized, and two amounts such as "5$ and 10$"
  no longer turn into a formula.
- A language episode interrupted by closing the app, or that failed to be written,
  is written again at the next start and when its language's home opens, instead of
  waiting for a session — never while Ollama is off.
- On a language's home, *Library* looks disabled when it is and says why; opening an
  episode from the library says it is loading, or that it could not be opened.
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

- **PDF engine updated**: pypdfium2 5.14.0 ships PDFium 156 (2026); 4.30.0 shipped
  the June 2024 engine, thirty Chrome security cycles behind, for the component that
  parses every imported file.
- The interactive API documentation is no longer served (it exposed the full API
  schema without the launch token).
- Exported logs no longer contain the path of your home folder (it appears as `~`),
  including in error traces.
- *Erase everything* also flushes SQLite's journal and removes the safety copy
  kept when a backup is restored.
- Build tooling: npm advisories fixed (`brace-expansion`, `source-map-js`, `undici`),
  KaTeX 0.18.11.

- The local API refuses requests that the browser itself marks as coming from another
  site or another local port (`Sec-Fetch-Site`). In browser mode, every port of
  127.0.0.1 counts as the same site and received the launch cookie.
- Release builds pin PyInstaller and its community hooks (`requirements-build.txt`,
  audited by `pip-audit`): a release no longer depends on whatever version PyPI
  serves that day.

[Unreleased]: https://github.com/cyyyp100/meta-capp/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/cyyyp100/meta-capp/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/cyyyp100/meta-capp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cyyyp100/meta-capp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/cyyyp100/meta-capp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/cyyyp100/meta-capp/releases/tag/v0.1.0
