#!/usr/bin/env python3
"""Smoke test UI réel : import PDF → sas → lecteur scroll libre → assistant.

Lance l'app sous un vrai ``mainloop()`` (comme en production : les threads LLM
marshalent via ``after``) et déroule un scénario événementiel sur un PDF de
test avec une DB temporaire.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "nwol"))

import config.settings as settings

_TMP = Path(tempfile.mkdtemp(prefix="nwol_smoke_"))
settings.DB_PATH = str(_TMP / "nwol.db")

FAILURES: list[str] = []
EXIT_CODE = [1]


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok" if condition else "ÉCHEC"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""), flush=True)
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # Aucun PDF n'est versionné : passer le sien en argument (ou NWOL_TEST_PDF).
    raw = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NWOL_TEST_PDF", "")
    pdf = Path(raw) if raw else None
    if pdf is None or not pdf.exists():
        print("Usage : python scripts/smoke_ui_block.py <fichier.pdf>")
        return 1

    import db as db_module
    from db.questions import count_assistant_questions
    from ui.app import NWoLApp

    app = NWoLApp()
    state = {"snapshot_page": None, "session_id": None, "pages_seen": 0}

    def finish() -> None:
        print(flush=True)
        if FAILURES:
            print(f"{len(FAILURES)} échec(s) : {FAILURES}", flush=True)
            EXIT_CODE[0] = 1
        else:
            print("Smoke test UI : tous les contrôles passent.", flush=True)
            EXIT_CODE[0] = 0
        try:
            app.on_close()
        except Exception:
            app.destroy()

    def guard(fn):
        def _wrapped():
            try:
                fn()
            except Exception:
                traceback.print_exc()
                FAILURES.append(f"exception dans {fn.__name__}")
                finish()
        return _wrapped

    # ── Étapes du scénario ────────────────────────────────────────────────
    def step_import() -> None:
        app.open_pdf_path(str(pdf))
        app.after(600, guard(step_check_sas))

    def step_check_sas() -> None:
        check("import → sas de concentration (pas de choix de chapitre)",
              app._current_view == "entry_sas", f"vue={app._current_view}")
        app._show_start_review()  # DB neuve : 0 carte → lecteur direct
        app.after(600, guard(step_check_reader))

    def step_check_reader() -> None:
        check("sas → lecteur scroll libre", app._current_view == "reader", f"vue={app._current_view}")
        check("session créée", app._session_mgr is not None)
        check("companion actif", app._companion is not None)
        check("bulle visible", bool(app.reader._bubble.place_info()))
        check("jauges absentes de l'UI", not hasattr(app.reader, "gauges"))
        state["session_id"] = app._session_mgr.session_id
        wait_until(lambda: len(app.reader._photos) >= 1, 25, "rendu progressif", step_after_render)

    def step_after_render() -> None:
        check("pages rendues progressivement", 1 in app.reader._photos, str(sorted(app.reader._photos)))
        app.reader._canvas.yview_moveto(0.3)
        app.after(1200, guard(step_after_scroll))

    def step_after_scroll() -> None:
        page = app._state.current_page
        check("page dominante mise à jour après scroll", page > 1, f"page={page}")
        check("pages vues accumulées", len(app._state.pages_seen) >= 2, str(sorted(app._state.pages_seen)))

        snap = app.reader.make_snapshot()
        check("snapshot : page du viewport", snap.page_number == page)
        check("snapshot : texte de page", len(snap.page_text) > 100)
        check("snapshot : image allégée", bool(snap.image_path) and Path(snap.image_path).exists())

        app.reader._toggle_panel()
        app.after(300, guard(step_ask_assistant))

    def step_ask_assistant() -> None:
        check("panneau assistant ouvert",
              app.reader._panel_visible and bool(app.reader._panel.place_info()))
        state["snapshot_page"] = app._state.current_page
        app.reader._on_user_question("Quel est le rôle du mécanisme d'attention décrit ici ?")
        # Scroll immédiat ailleurs : la réponse doit rester ancrée à la page du submit.
        app.reader._canvas.yview_moveto(0.85)
        wait_until(lambda: count_assistant_questions(state["session_id"]) >= 1,
                   180, "réponse assistant", step_check_exchange)

    def step_check_exchange() -> None:
        sid = state["session_id"]
        ok = count_assistant_questions(sid) >= 1
        check("question libre → ligne questions(assistant_follow_up)", ok)
        if ok:
            row = db_module.get_connection().execute(
                "SELECT page_start, answer FROM questions "
                "WHERE session_id=? AND scope_type='assistant_follow_up'", (sid,),
            ).fetchone()
            check("réponse ancrée à la page du submit", row["page_start"] == state["snapshot_page"],
                  f"page_start={row['page_start']} attendu={state['snapshot_page']}")
            check("réponse LLM non vide", bool((row["answer"] or "").strip()))
            check("dernier échange mémorisé", app.reader._last_exchange is not None)
            if app.reader._last_exchange:
                app.reader._create_flashcard_from_answer()
        app.after(400, guard(step_check_flashcard))

    def step_check_flashcard() -> None:
        sid = state["session_id"]
        n_cards = db_module.get_connection().execute(
            "SELECT COUNT(*) FROM flashcards WHERE session_id=? AND source='manual'", (sid,),
        ).fetchone()[0]
        check("flashcard manuelle créée", n_cards == 1, str(n_cards))
        n_gauges = db_module.get_connection().execute(
            "SELECT COUNT(*) FROM session_gauges WHERE session_id=?", (sid,),
        ).fetchone()[0]
        check("jauges enregistrées en base", n_gauges > 0, str(n_gauges))

        state["pages_seen"] = len(app._state.pages_seen)
        app._on_session_end()
        app.after(800, guard(step_check_exit))

    def step_check_exit() -> None:
        check("fin → sas de sortie", app._current_view == "exit_sas", f"vue={app._current_view}")
        session = db_module.get_connection().execute(
            "SELECT pages_read FROM reading_sessions WHERE id=?", (state["session_id"],),
        ).fetchone()
        check("pages_read = pages vues", session["pages_read"] == state["pages_seen"],
              f"pages_read={session['pages_read']} vues={state['pages_seen']}")
        finish()

    def wait_until(predicate, timeout_s: float, label: str, next_step) -> None:
        deadline = time.monotonic() + timeout_s

        def _poll() -> None:
            try:
                done = predicate()
            except Exception:
                done = False
            if done:
                guard(next_step)()
            elif time.monotonic() > deadline:
                print(f"[timeout] {label} ({timeout_s}s)", flush=True)
                FAILURES.append(f"timeout {label}")
                guard(next_step)()
            else:
                app.after(250, _poll)

        app.after(250, _poll)

    app.after(400, guard(step_import))
    app.after(420_000, guard(finish))  # garde-fou global
    app.mainloop()
    shutil.rmtree(_TMP, ignore_errors=True)
    return EXIT_CODE[0]


if __name__ == "__main__":
    sys.exit(main())
