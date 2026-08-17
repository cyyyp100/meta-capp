# Contributing to Meta-Capp

Thanks for being here. Meta-Capp is a local-first learning companion, and it gets
better every time someone tests it against a real document, a real learner, or a real
edge case.

Issues and pull requests are welcome in **English or French** — whichever you are
more comfortable writing.

---

## Ways to help

| | |
|---|---|
| 🐛 **Bug reports** | Especially PDF edge cases: unusual layouts, huge files, exotic fonts, RTL, scanned pages. |
| 🎓 **Pedagogy** | Prompt quality, intervention timing, gauge formulas, flashcard usefulness. |
| ♿ **Accessibility** | Keyboard navigation, contrast, screen readers, reduced motion. |
| 🌍 **Translations** | The FR/EN dictionaries are `nwol/i18n.py` and `frontend/src/i18n/index.ts`. |
| 📚 **Docs** | If the README or this guide is stale or unclear, say so — or fix it. |

---

## Scope: what belongs in this repository

This repository is the **local edition**: 100 % offline, Ollama only, no account, no
activation, no network call beyond `127.0.0.1:11434`.

Please do **not** submit code that:

- calls a remote/hosted API or any third-party service,
- verifies a subscription, licence key or account,
- gates an existing feature behind a plan,
- adds analytics, telemetry, crash reporting or any outbound request.

Those belong to the separate Pro edition. A PR that adds them will be declined even if
the code is excellent — it is a product boundary, not a quality judgment.

---

## Development setup

```bash
git clone https://github.com/cyyyp100/meta-capp.git
cd meta-capp

# Python 3.11 — conda is what the project is developed against
conda create -n nwol python=3.11.9 && conda activate nwol
# ...or a plain venv:  python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
cd frontend && npm install && cd ..

ollama pull gemma4:e4b      # optional: the app degrades gracefully without it

python main.py              # native app window
```

Install the quality hooks (ruff + gitleaks run before each commit):

```bash
pip install pre-commit && pre-commit install
```

---

## Before you open a pull request

Run the same checks CI runs:

```bash
cd nwol && python -m pytest                     # backend suite
cd nwol && ruff check .                         # lint
python -m compileall nwol                       # static import/syntax check
cd frontend && npm run build && npx vitest run  # type-check, bundle, UI tests
python desktop/pywebview_main.py --server-only  # headless server smoke test
```

---

## Conventions that matter here

Six house rules hold this codebase together. They are the ones that most often trip
newcomers up, and a pull request that breaks them will be sent back:

1. **Absolute imports rooted at `nwol/`.** Write `from services import ...`, never
   `from nwol.services import ...`. Entry points put `nwol/` on `sys.path`.
2. **Behaviour lives in `nwol/services/`.** Never in a router, never in a React
   component. Routers translate HTTP/WebSocket to service calls and back.
3. **Single source of truth.** A router must not re-implement a policy a service owns,
   and a threshold must not be a literal where `nwol/config/settings.py` declares it.
4. **Schema changes are versioned.** Bump `DB_SCHEMA_VERSION` and add an idempotent
   step in `nwol/db/migrations.py`. Never edit an existing table in place.
5. **i18n stays in sync.** A new user-facing string means a new key in *both*
   dictionaries (FR and EN).
6. **Tests live in `nwol/tests/{server,services}`.** New behaviour ships with a test.

---

## Commits and pull requests

- Keep commits focused; a readable history is worth more than a perfect one.
- Describe *why*, not only *what* — the intent is what reviewers cannot reconstruct.
- Link the issue the PR closes, and say how you verified it (commands, PDF used, OS).
- Small PRs get merged. Large refactors are much easier to accept if you open an issue
  first and agree on the shape.

---

## Code of Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). Be the kind of
reviewer you would want on your own first pull request.

## Security

Do not open a public issue for a vulnerability — follow [SECURITY.md](SECURITY.md).

## Licensing of contributions

By submitting a contribution you agree that it is licensed under the
[MIT License](LICENSE) that covers this project.
