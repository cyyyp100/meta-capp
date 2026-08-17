<div align="center">

# Meta-Capp

### The AI-native cognitive learning companion for educational PDFs

**Your PDF, exactly as its author designed it — with a living AI reading companion beside it that watches how you learn, answers in context, and speaks up only when it actually helps.**

[![License: MIT](https://img.shields.io/badge/License-MIT-000000.svg?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/cyyyp100/meta-capp/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/cyyyp100/meta-capp/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20LLM-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.com)
[![100% offline](https://img.shields.io/badge/100%25-offline-2ea44f?style=flat-square)](#why-local-ai-matters)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-blueviolet?style=flat-square)](CONTRIBUTING.md)

[**Why**](#the-core-idea) · [**Features**](#core-features) · [**Install**](#installation) · [**Architecture**](#tech-stack) · [**Editions**](#editions--local-vs-pro) · [**Contributing**](CONTRIBUTING.md)

</div>

---

<div align="center">

|  |  |  |
|:--:|:--:|:--:|
| **📄 Zero reconstruction** | **🧠 Silent cognitive engine** | **🔒 Nothing leaves your machine** |
| The PDF is rendered as-is, full fidelity, free scroll. No chunking, no re-layout, no gates. | Six hidden gauges, adaptive questions, flashcards and session memory run behind the page. | Local inference via Ollama. No account, no telemetry, no cloud, no subscription. |

</div>

---

## The Core Idea

Large Language Models have made information access almost effortless.

**But effortless access is not learning.**

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

**The goal is to help the learner build a stronger mind.**

---

## What Meta-Capp Is

Meta-Capp does **not** try to reproduce or reconstruct the PDF. The document is displayed exactly as its author designed it — full pages, free scrolling, no locks, no gates.

What changes is everything *around* the document:

<table>
<tr>
<td width="50%" valign="top">

### 📖 A free-scroll reader

The whole PDF, rendered progressively page by page, at full fidelity. You read at your own pace.

</td>
<td width="50%" valign="top">

### 👁️ An embodied assistant — Gemma

A small animated bubble floats over the PDF. It has eyes. It reads when you read, thinks when you ask, sleeps when the local model is offline. Click it, ask anything: the answer is grounded in the exact page visible at the moment you press *Send* — even if you scroll away while it thinks.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🧩 A silent pedagogical engine

Behind the scenes, the full metacognitive system keeps running: sessions, cognitive gauges, adaptive questions, evaluated answers, automatic flashcards, end-of-session reflection. The gauges are no longer displayed during reading — they are computed, recorded, and fed to the AI instead of being shoved in your face.

</td>
<td width="50%" valign="top">

### ✋ Autonomous interventions

The assistant notices when you linger on a page, keep coming back to it, ask repeated questions about the same passage, or face a math-heavy wall. It then *decides* — via the LLM — whether to offer help, ask a pedagogical question, suggest a pause, or offer to rephrase the page. Cooldowns keep it from being chatty. A *discret* mode silences it entirely; a *coach* mode makes it bolder.

</td>
</tr>
</table>

---

## Why This Project Exists

> **Educational PDFs are cognitively dead interfaces.**

- Traditional readers display pages.
- Traditional chatbots answer questions without context.
- Traditional RAG pipelines chunk text and lose the document.

None of them understand learners.

Learning is an active cognitive process involving attention, memory, uncertainty, reflection, confusion, reconstruction, and effort.

Meta-Capp was designed to restore these mechanisms in the age of AI — **without getting between the reader and the document.**

---

## A Different Philosophy of AI

Most AI educational systems try to remove friction.

Meta-Capp introduces **productive friction** — but never imposed friction.

Earlier prototypes locked page turns behind questions. This version trusts the reader: scrolling is free, and the system earns attention instead of demanding it. The assistant:

- answers from the visible page first, general knowledge second,
- asks real pedagogical questions whose answers are evaluated,
- converts good exchanges into flashcards,
- updates a cognitive profile from everything you do,
- and closes each session with metacognitive reflection.

> AI is not used to replace thinking.
> **AI is used to improve thinking.**

---

## Why Local AI Matters

Meta-Capp runs entirely locally using **Gemma 4 through [Ollama](https://ollama.com)**.

| ❌ No subscriptions | ❌ No cloud dependency | ❌ No educational surveillance | ❌ No data harvesting |
|---|---|---|---|

Educational data stays on the learner's machine: mistakes, doubts, weaknesses, confusion, curiosity, reflection. **These should not become cloud products.**

If Ollama is offline, nothing breaks: the reader stays fully usable and the assistant visibly falls asleep.

---

## Core Features

| Capability | Description |
|---|---|
| **Free-Scroll PDF Reader** | Full document, progressive high-res page rendering, no progression locks |
| **Embodied Assistant Bubble** | Animated, draggable Canvas character with idle / reading / thinking / answering / intervention / sleeping states |
| **Submit-Time Context Capture** | Every question is answered against a snapshot of the page visible at the exact moment you press Send |
| **Autonomous Interventions** | LLM-decided help offers, questions, pause suggestions, page rephrasings — with global and per-page cooldowns |
| **Assistant Modes** | *discret* (never speaks first), *normal*, *coach* (intervenes more) — persisted per user |
| **Adaptive Questioning** | Full question → answer → evaluation → feedback → flashcard pipeline, non-blocking |
| **Hidden Cognitive Gauges** | Attention, comprehension, curiosity, retention, creativity, metacognition — computed and recorded, never nagging |
| **Session Memory** | Pages seen, dwell time, revisits, questions per page, detected difficulties |
| **Manual Flashcards** | One click turns a useful assistant answer into a flashcard |
| **Enriched Session Summary** | End-of-session synthesis includes the pages where you asked for the most help |
| **Chapter Awareness** | Chapter index computed (TOC or font-size heuristics) as metadata for the AI and the nav bar |
| **Source-Code Reading** | Import a source file: it is paginated into readable code blocks with the same companion on top |
| **Bilingual (FR / EN)** | UI *and* LLM prompt language switch together, persisted across launches |
| **Fully Local AI** | Gemma 4 via Ollama, graceful degradation when offline |

---

## The Reading Flow

```
  Import  →  Airlock  →  Flash review  →  Free reading  →  Challenge  →  Synthesis
```

1. **Import a PDF.** No chapter selection — the whole document is the session.
2. **Concentration airlock.** A 30-second slowdown ritual with an AI-generated curiosity hook.
3. **Flash review.** Up to 5 due flashcards from this document.
4. **Read freely.** The full PDF, scrollable, with Gemma floating above it.
5. **Ask anything.** Click the bubble, type, press Enter. The answer cites the page you were on when you asked.
6. **Get challenged.** Sometimes Gemma asks *you* a question. Answer it (it is evaluated, it feeds your profile, it may become a flashcard) — or close it.
7. **End the session.** Synthesis, metacognitive questions, profile update.

---

## The Role of Gemma 4

<table>
<tr><td width="50%" valign="top">

**Contextual Answering**
Answers user questions from a `PageContextSnapshot`: page text, a lightweight page image, estimated chapter, live gauges, and recent exchanges.

</td><td width="50%" valign="top">

**Intervention Decisions**
Receives observed signals (dwell time, revisits, low attention, math density, repeated questions) and returns a structured decision:
`{should_intervene, kind, message, question}`.

</td></tr>
<tr><td width="50%" valign="top">

**Educational Generation**
Adaptive questions, answer evaluation with metacognitive signals, rephrasings, flashcards, curiosity hooks.

</td><td width="50%" valign="top">

**Metacognitive Analysis**
End-of-session summaries, reflection questions, and profile updates.

</td></tr>
</table>

---

## Cognitive Profile System

Six gauges evolve during every session and consolidate into a long-term profile: **context comprehension, creativity, retention, curiosity, attention, metacognition** — plus per-subject levels detected from your documents.

During reading they are invisible. They still drive everything: question difficulty, intervention thresholds, session summaries, and the assistant's tone.

---

## Installation

### Requirements

- **Python 3.11**
- **Node 20+** (to build the web UI)
- **[Ollama](https://ollama.com)** running locally

### Pull the model

```bash
ollama pull gemma4:e4b
```

> Without Ollama the app still runs: reader, flashcards and stats work, and the assistant visibly falls asleep.

### Setup

```bash
git clone https://github.com/cyyyp100/meta-capp.git
cd meta-capp

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### Launch

```bash
python main.py                       # native app window (builds the frontend if needed)
python main.py path/to/document.pdf  # import and open a document directly
python main.py --debug               # DEBUG logging
```

For iteration, backend and frontend can run standalone:

```bash
cd nwol && python -m server.main     # FastAPI on 127.0.0.1:8756
cd frontend && npm run dev           # Vite on :5173, proxies /api
```

<details>
<summary><b>Packaging a desktop binary</b></summary>

```bash
cd frontend && npm run build && cd ..            # build the UI first
pyinstaller desktop/metacapp.spec --noconfirm    # output in dist_app/
```

</details>

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| PDF Rendering | **PyMuPDF** | Page rendering, page text, chapter detection |
| Semantic Intelligence | **Gemma 4 via Ollama** | Contextual answers, interventions, educational reasoning |
| Cognitive Engine | **Custom metacognitive system** | Gauges, profile, reflection, session memory |
| UI | **FastAPI + React (Vite) in pywebview** | Reader, floating assistant, stats, flashcards, languages |
| Persistence | **SQLite** | Documents, sessions, questions, answers, gauges, flashcards, preferences |

**Shape of the codebase** — UI-agnostic business logic lives in `nwol/services/`; the FastAPI app and its routers in `nwol/server/`; the reader is a WebSocket stream; the desktop shell is `desktop/pywebview_main.py`. The conventions that keep it that way are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

```
meta-capp/
├── main.py               # entry point — launches the desktop app
├── desktop/              # native shell (pywebview) + PyInstaller spec
├── frontend/             # React 18 + Vite + TypeScript UI
└── nwol/
    ├── services/         # ← business logic: the single home for behaviour
    ├── server/           # FastAPI app factory + routers mounted under /api
    ├── llm/              # Ollama client, prompts, JSON schemas
    ├── metacog/          # gauges, long-term profile, reflection
    ├── db/               # SQLite connection + versioned migrations
    ├── config/           # settings — the source of truth for every threshold
    └── tests/            # backend + services suites
```

---

## Verification

```bash
cd nwol && python -m pytest                     # backend suite
cd nwol && ruff check .                         # lint
cd frontend && npm run build && npx vitest run  # type-check, bundle, UI tests
python -m compileall nwol                       # static check
python desktop/pywebview_main.py --server-only  # headless server smoke test
```

CI runs the backend suite, the frontend build and the security scans (`pip-audit`, `npm audit`, secret scanning) on every push and pull request.

---

## Editions — Local vs Pro

**This repository is the complete local edition, and it is free forever under the MIT license.** It is not a crippled demo: the reader, the assistant, the metacognitive engine, the gauges, the flashcards and the session memory are all here, all working, all offline.

Meta-Capp **Pro** is a separate, hosted edition for people who want the same pedagogy without owning a GPU — and with capabilities a small local model simply cannot deliver.

| | **Local** — this repo | **Pro** — hosted |
|---|:--:|:--:|
| Price | **Free**, MIT | Subscription |
| Setup | Install Ollama, pull a model | Nothing to install |
| Inference | On your machine (`gemma4:e4b`) | Frontier hosted models via API |
| Answer depth on hard material | Bounded by your hardware | Full-size reasoning models |
| Renders any PDF as-is | ✅ | ✅ |
| Scanned / handwritten PDFs | ❌ | ✅ **OCR reconstruction** |
| Semantic re-layout of messy documents | ❌ | ✅ |
| Voice — talk to Gemma, listen back | ❌ | ✅ **Speech** |
| Works with zero GPU / low-end laptop | Degraded | ✅ |
| Cognitive engine, gauges, flashcards | ✅ | ✅ |
| Your data stays local | ✅ Always | Processing is remote |
| Support | Community issues | Priority |

> **Interested in Pro, a school/university deployment, or early access?**
> Open a [discussion](https://github.com/cyyyp100/meta-capp/discussions) — that is the fastest way to reach the maintainer.

Contributions to this repository stay in this repository, under MIT. Anything that talks to a remote service, verifies a subscription, or gates a feature behind a plan does **not** belong here — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Your Data

Everything Meta-Capp knows about you sits in one SQLite file on your own disk —
`data/nwol.db` when running from source, the OS application-data directory when packaged
(`~/Library/Application Support/Meta-Capp/` on macOS).

- **No telemetry, no tracking, no automatic crash reports.**
- **No account, no activation, no key to enter.**
- The application server listens on `127.0.0.1` and refuses anything coming from
  elsewhere. The only possible outbound connection is to Ollama, on your own machine.
- **Portability**: export everything in one click (Profile → *My data*) — it is a
  standard SQLite file you can open yourself.
- **Erasure**: an *Erase everything* button wipes profile, questions, flashcards,
  documents and logs. Deleting the application data folder removes the rest. Nothing
  survives anywhere else.

---

## Contributing

Issues, ideas and pull requests are welcome — especially around pedagogy, accessibility, and PDF edge cases.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions and the review checklist.
- By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
- Found a vulnerability? Please follow [SECURITY.md](SECURITY.md) rather than opening a public issue.

If Meta-Capp resonates with you, **star the repo** — it is the cheapest way to help it reach the learners it was built for.

---

## Educational Philosophy

Meta-Capp is built around one core idea:

> ### AI should not make humans cognitively passive.

The future of educational AI should not be instant answers, automated thinking, and dependency loops. It should help humans reason better, remember longer, reflect deeper, and remain intellectually active.

Meta-Capp explores what educational software becomes when AI is used not to replace cognition, but to strengthen it — and when the AI itself becomes a discreet, embodied presence beside the document instead of a wall between the reader and the page.

---

## License

Released under the [MIT License](LICENSE) — © 2026 Cyprien Vial.

Third-party components keep their own licenses (PyMuPDF is AGPL/commercial-dual-licensed; check its terms before redistributing a closed-source derivative).

