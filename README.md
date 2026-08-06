# Meta-Capp
## AI-Native Cognitive Learning Companion for Educational PDFs

> Meta-Capp opens your educational PDFs as they are — and gives you a living, local AI reading companion that watches how you learn, answers in context, and intervenes only when it helps.

---

# The Core Idea

Large Language Models have made information access almost effortless.

But effortless access is not learning.

Modern AI tools often encourage:
- passive consumption,
- instant answers,
- intellectual dependency,
- shallow understanding,
- and the illusion of competence.

Meta-Capp was built from the opposite philosophy.

Instead of replacing effort, it uses AI to **structure effort intelligently**.

Instead of optimizing for “fast answers”, it optimizes for:
- comprehension,
- reflection,
- retention,
- curiosity,
- and metacognitive awareness.

The goal is not to make the learner passive.

The goal is to help the learner build a stronger mind.

---

# What Meta-Capp Is

Meta-Capp does **not** try to reproduce or reconstruct the PDF. The document is
displayed exactly as its author designed it — full pages, free scrolling, no
locks, no gates.

What changes is everything *around* the document:

- **A free-scroll reader.** The whole PDF, rendered progressively page by page,
  at full fidelity. You read at your own pace.
- **An embodied assistant — Gemma.** A small animated bubble floats over the
  PDF. It has eyes. It reads when you read, thinks when you ask, sleeps when
  the local model is offline. Click it, ask anything: the answer is grounded in
  the exact page visible at the moment you press *Send* — even if you scroll
  away while it thinks.
- **A silent pedagogical engine.** Behind the scenes, the full metacognitive
  system keeps running: sessions, cognitive gauges, adaptive questions,
  evaluated answers, automatic flashcards, end-of-session reflection. The
  gauges are no longer displayed during reading — they are computed, recorded,
  and fed to the AI instead of being shoved in your face.
- **Autonomous interventions.** The assistant notices when you linger on a
  page, keep coming back to it, ask repeated questions about the same passage,
  or face a math-heavy wall. It then *decides* — via the LLM — whether to offer
  help, ask a pedagogical question, suggest a pause, or offer to rephrase the
  page. Cooldowns keep it from being chatty. A *discret* mode silences it
  entirely; a *coach* mode makes it bolder.

---

# Why This Project Exists

Educational PDFs are cognitively dead interfaces.

Traditional readers display pages.
Traditional chatbots answer questions without context.
Traditional RAG pipelines chunk text and lose the document.

None of them understand learners.

Learning is an active cognitive process involving:
- attention,
- memory,
- uncertainty,
- reflection,
- confusion,
- reconstruction,
- and effort.

Meta-Capp was designed to restore these mechanisms in the age of AI — without
getting between the reader and the document.

---

# A Different Philosophy of AI

Most AI educational systems try to remove friction.

Meta-Capp introduces **productive friction** — but never imposed friction.

Earlier prototypes locked page turns behind questions. This version trusts the
reader: scrolling is free, and the system earns attention instead of demanding
it. The assistant:

- answers from the visible page first, general knowledge second,
- asks real pedagogical questions whose answers are evaluated,
- converts good exchanges into flashcards,
- updates a cognitive profile from everything you do,
- and closes each session with metacognitive reflection.

AI is not used to replace thinking.

AI is used to improve thinking.

---

# Why Local AI Matters

Meta-Capp runs entirely locally using Gemma 4 through Ollama.

No subscriptions.
No cloud dependency.
No educational surveillance.
No data harvesting.

Educational data stays on the learner’s machine: mistakes, doubts, weaknesses,
confusion, curiosity, reflection. These should not become cloud products.

If Ollama is offline, nothing breaks: the reader stays fully usable and the
assistant visibly falls asleep.

---

# Core Features

| Capability | Description |
|---|---|
| **Free-Scroll PDF Reader** | Full document, progressive high-res page rendering, no progression locks |
| **Embodied Assistant Bubble** | Animated, draggable Canvas character with idle / reading / thinking / answering / intervention / sleeping states |
| **Submit-Time Context Capture** | Every question is answered against a snapshot of the page visible at the exact moment you press Send |
| **Autonomous Interventions** | LLM-decided help offers, questions, pause suggestions, page rephrasings — with global and per-page cooldowns |
| **Assistant Modes** | *discret* (never speaks first), *normal*, *coach* (intervenes more) — persisted per user |
| **Adaptive Questioning** | Full question → answer → evaluation → feedback → flashcard pipeline, now non-blocking |
| **Hidden Cognitive Gauges** | Attention, comprehension, curiosity, retention, creativity, metacognition — computed and recorded, never nagging |
| **Session Memory** | Pages seen, dwell time, revisits, questions per page, detected difficulties |
| **Manual Flashcards** | One click turns a useful assistant answer into a flashcard |
| **Enriched Session Summary** | End-of-session synthesis includes the pages where you asked for the most help |
| **Chapter Awareness** | Chapter index still computed (TOC or font-size heuristics) as metadata for the AI and the nav bar |
| **Fully Local AI** | Gemma 4 via Ollama, graceful degradation when offline |

---

# The Reading Flow

1. **Import a PDF.** No chapter selection — the whole document is the session.
2. **Concentration airlock.** A 30-second slowdown ritual with an AI-generated
   curiosity hook.
3. **Flash review.** Up to 5 due flashcards from this document.
4. **Read freely.** The full PDF, scrollable, with Gemma floating above it.
5. **Ask anything.** Click the bubble, type, press Enter. The answer cites the
   page you were on when you asked.
6. **Get challenged.** Sometimes Gemma asks *you* a question. Answer it (it is
   evaluated, it feeds your profile, it may become a flashcard) — or close it.
7. **End the session.** Synthesis, metacognitive questions, profile update.

---

# The Role of Gemma 4

## Contextual Answering
Answers user questions from a `PageContextSnapshot`: page text, a lightweight
page image, estimated chapter, live gauges, and recent exchanges.

## Intervention Decisions
Receives observed signals (dwell time, revisits, low attention, math density,
repeated questions) and returns a structured decision:
`{should_intervene, kind, message, question}`.

## Educational Generation
Adaptive questions, answer evaluation with metacognitive signals, rephrasings,
flashcards, curiosity hooks.

## Metacognitive Analysis
End-of-session summaries, reflection questions, and profile updates.

---

# Cognitive Profile System

Six gauges evolve during every session and consolidate into a long-term
profile: context comprehension, creativity, retention, curiosity, attention,
metacognition — plus per-subject levels detected from your documents.

During reading they are invisible. They still drive everything: question
difficulty, intervention thresholds, session summaries, and the assistant’s
tone.

---

# Installation

## Requirements

- Python 3.11
- Node 20+ (to build the web UI)
- [Ollama](https://ollama.com) running locally

## Pull the model

```bash
ollama pull gemma4:e4b
```

Without Ollama the app still runs: reader, flashcards and stats work, and the
assistant visibly falls asleep.

## Setup

```bash
git clone https://github.com/cyyyp100/meta-capp.git
cd meta-capp

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## Launch

```bash
python main.py --web                 # web UI in a native window (builds the frontend)
python main.py                       # legacy Tkinter UI
python main.py path/to/document.pdf  # open a PDF directly
```

For iteration, backend and frontend can run standalone:

```bash
cd nwol && python -m server.main     # FastAPI on 127.0.0.1:8756
cd frontend && npm run dev           # Vite on :5173, proxies /api
```

---

# Tech Stack

| Layer | Technology | Role |
|---|---|---|
| PDF Rendering | PyMuPDF + PIL | Page rendering, page text, chapter detection |
| Semantic Intelligence | Gemma 4 via Ollama | Contextual answers, interventions, educational reasoning |
| Cognitive Engine | Custom Metacognitive System | Gauges, profile, reflection, session memory |
| Web UI | FastAPI + React (Vite) in pywebview | Reader, floating assistant, stats, flashcards, languages |
| Legacy UI | Tkinter | Free-scroll reader + Canvas assistant bubble |
| Persistence | SQLite | Documents, sessions, questions, answers, gauges, flashcards, preferences |

---

# Verification

```bash
cd nwol && python -m pytest                     # backend suite
cd frontend && npm run build && npx vitest run  # type-check, bundle, UI tests
python -m compileall nwol                       # static check
python scripts/verify_block_refonte.py          # DB migration + logic suite (no UI)
python scripts/smoke_ui_block.py path/to.pdf    # full Tk UI scenario
```

---

# Educational Philosophy

Meta-Capp is built around one core idea:

> AI should not make humans cognitively passive.

The future of educational AI should not be instant answers, automated thinking,
and dependency loops. It should help humans reason better, remember longer,
reflect deeper, and remain intellectually active.

Meta-Capp explores what educational software becomes when AI is used not to
replace cognition, but to strengthen it — and when the AI itself becomes a
discreet, embodied presence beside the document instead of a wall between the
reader and the page.
