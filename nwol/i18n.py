# i18n.py — Chaînes produites côté serveur (FR / EN) : menu natif, messages du
# lecteur et du module Langues, erreurs renvoyées par l'API. L'interface web a
# son propre dictionnaire (frontend/src/i18n/index.ts) ; la langue choisie pilote
# aussi celle des prompts LLM.
from __future__ import annotations

_lang: str = "fr"

STRINGS: dict[str, dict[str, str]] = {
    "fr": {
        # ── Home ──────────────────────────────────────────────────────────
        "home.subtitle": "Compagnon d'apprentissage adaptatif",
        # ── App / menu ────────────────────────────────────────────────────
        # Barre de menu NATIVE (desktop/pywebview_main.py). Ces libellés sont
        # figés au démarrage : pywebview construit le menu une fois, avant tout
        # changement de langue en cours de session.
        "menu.file": "Fichier",
        "menu.open_pdf": "Ouvrir un document…",
        "menu.library": "Bibliothèque",
        "menu.settings": "Réglages…",
        # Coque de secours : interface dans le navigateur (desktop/pywebview_main.py).
        # Écrit dans le terminal, jamais dans les logs (l'adresse porte le nonce).
        "desktop.browser_mode": "Meta-Capp est ouvert dans votre navigateur : {url}",
        "desktop.browser_not_opened": "Le navigateur ne s'est pas ouvert tout seul : copiez l'adresse ci-dessus dans votre navigateur.",
        "desktop.files_readable": "Documents lisibles",
        "desktop.files_code": "Fichiers de code",
        "desktop.files_all": "Tous les fichiers",
        "desktop.browser_quit": "Pour quitter : « Quitter Meta-Capp » dans le menu du profil, ou fermez l'onglet (arrêt automatique {minutes} min plus tard), ou Ctrl+C ici.",
        "menu.view": "Affichage",
        "menu.zoom_in": "Agrandir",
        "menu.zoom_out": "Réduire",
        "menu.theme_light": "Thème clair",
        "menu.theme_dark": "Thème sombre",
        "menu.fullscreen": "Plein écran",
        "menu.help": "Aide",
        "menu.tutorial": "Tutoriel",
        "menu.report_issue": "Signaler un problème",
        "menu.rate": "Noter Meta-Capp",
        "menu.check_updates": "Vérifier les mises à jour…",
        "menu.about": "À propos",
        # ── Bulle assistante ──────────────────────────────────────────────
        "assistant.mode_changed": "Mode d'accompagnement : {mode}",
        "assistant.cancelled": "Demande annulée.",
        # ── Sas de sortie ─────────────────────────────────────────────────
        "session.reflection_q1": "Qu'as-tu compris de plus important dans cette session ?",
        "session.reflection_q2": "Quel point reste flou et mériterait d'être revu ?",
        "session.reflection_n": "Réflexion {n}",
        "assistant.failed": "Clikoda n'a pas pu traiter cette demande. Réessaie.",
        "assistant.mode_discret": "Discret",
        "assistant.mode_normal": "Normal",
        "assistant.mode_coach": "Coach",
        "assistant.review_toast": "Une flashcard est à réviser : {front}",
        "assistant.review_action": "Réviser",
        "assistant.review_done": "Révision enregistrée ✓",
        "assistant.flashcard_review_title": "Flashcard à réviser",
        "assistant.review_reveal": "Voir la réponse",
        "assistant.review_correct": "✓ Su",
        "assistant.review_partial": "~ Presque",
        "assistant.review_incorrect": "✗ Oublié",
        "assistant.focus_btn": "🎯 Mode focus",
        "assistant.focus_stop": "🎯 Arrêter le focus",
        "focus.started": "Mode focus : aucune intervention pendant {minutes} min. Bonne lecture !",
        "focus.ended": "Focus terminé — une courte pause peut faire du bien.",
        "focus.stopped": "Mode focus arrêté.",
        # ── Fin de chapitre ──────────────────────────────────────────────
        "reader.chapter_done": "Chapitre terminé 🎉 {title}",
        "reader.chapter_recap_action": "Récap",
        "reader.chapter_recap_loading": "Préparation du récap de « {title} »…",
        "reader.next_chapter_tease": "👀 Chapitre suivant — {title} : {hook}",
        # ── Inline Q&A ───────────────────────────────────────────────────
        "qa.mask_placeholder": "réponse masquée temporairement",
        "qa.low_attention_hint": "Ton attention semble basse : prends une pause courte, puis reviens répondre simplement.",
        "qa.criteria_faithful": "Réponse fidèle au passage fourni.",
        # ── Bibliothèque : dossiers ───────────────────────────────────────
        "folders.default_name": "Nouveau dossier",
        "folders.missing": "Dossier introuvable.",
        "folders.parent_missing": "Dossier de destination introuvable.",
        "folders.document_missing": "Document introuvable.",
        "folders.cycle": "Un dossier ne peut pas être déplacé dans l'un de ses sous-dossiers.",
        "folders.too_deep": "Arborescence trop profonde (maximum {n} niveaux).",
        "brainstorm.missing": "Discussion introuvable.",
        "brainstorm.folder_missing": "Dossier introuvable.",
        "brainstorm.pin_limit": "{n} discussions épinglées au maximum : désépingles-en une d'abord.",
        "brainstorm.busy": "Clikoda répond déjà dans cette discussion : attends sa réponse.",
        "brainstorm.failed": "Clikoda n'a pas pu traiter ce message. Réessaie dans un instant.",
        # Portrait d'une langue cité par le brainstorming (services/brainstorm_search.language_sources).
        "brainstorm.lang.level": "niveau {level}",
        "brainstorm.lang.program": "programme : point {order} sur {size}",
        "brainstorm.lang.last_today": "dernière séance : aujourd'hui",
        "brainstorm.lang.last_days": "dernière séance : il y a {n} j",
        "brainstorm.lang.no_study_day": "aucun jour d'étude compté",
        "brainstorm.lang.days": "jours d'étude : {d7} sur les 7 derniers, {d28} sur les 28 derniers",
        "brainstorm.lang.minutes": "temps passé : ≈ {m} min par jour d'étude",
        "brainstorm.lang.episodes": "épisodes joués : {n}",
        "brainstorm.lang.words": "mots rencontrés : {seen}, dont acquis : {acquired}",
        "brainstorm.lang.difficulty": "dernières séances : {detail}",
        "brainstorm.lang.easy": "facile",
        "brainstorm.lang.ok": "adaptée",
        "brainstorm.lang.hard": "difficile",
        # Mots et épisodes du module Langues cités par le brainstorming.
        "brainstorm.word.entry": "{word} → {translation}",
        "brainstorm.word.acquired": "acquis",
        "brainstorm.word.learning": "pas encore acquis",
        "brainstorm.word.met": "rencontré à l'épisode {n}",
        "brainstorm.episode": "épisode {n} « {title} »",
        "brainstorm.episode.line": "{speaker} : « {text} » ({translation})",
        "library.title_empty": "Le titre ne peut pas être vide.",
        "library.bookmark_page_invalid": "Cette page n'existe pas dans le document.",
        # Prise de notes (services/annotations) : noms des étiquettes prédéfinies,
        # export Markdown du carnet, refus renvoyés tels quels à l'interface.
        "annotations.preset.important": "Important",
        "annotations.preset.definition": "Définition",
        "annotations.preset.example": "Exemple",
        "annotations.preset.review": "À revoir",
        "annotations.preset.question": "Question",
        "annotations.preset.idea": "Idée",
        "annotations.md.title": "Notes — {title}",
        "annotations.md.bookmark_line": "**Marque-page** : page {page}",
        "annotations.md.signets": "Signets",
        "annotations.md.page": "Page {page}",
        "annotations.md.sticky": "Post-it",
        "annotations.md.no_label": "Sans étiquette",
        "annotations.md.empty": "Aucune note sur ce document.",
        "annotations.md.file_suffix": "notes",
        "annotations.md.style.highlight": "surligné",
        "annotations.md.style.underline": "souligné",
        "annotations.md.style.strike": "barré",
        "annotations.md.style.outline": "encadré",
        "annotations.error.missing": "Cette note n'existe plus.",
        "annotations.error.color": "Couleur inconnue.",
        "annotations.error.style": "Style de surlignage inconnu.",
        "annotations.error.kind": "Type de note inconnu.",
        "annotations.error.label_name": "Le nom d'une étiquette fait de 1 à {max} caractères.",
        "annotations.error.label_missing": "Cette étiquette n'existe plus.",
        "annotations.error.label_limit": "{max} étiquettes au plus.",
        "annotations.error.last_label": "Il faut garder au moins une étiquette.",
        "annotations.error.label_order": "L'ordre doit reprendre toutes les étiquettes, une fois chacune.",
        "annotations.error.too_long": "{max} caractères au plus.",
        "annotations.error.quote": "Le passage surligné est vide ou dépasse {max} caractères.",
        "annotations.error.rects": "Zone de surlignage invalide.",
        "annotations.error.position": "Position du post-it invalide.",
        # « Localiser le fichier » (services/relink) : refus traduits, renvoyés
        # tels quels par le serveur et affichés par l'interface.
        "library.file_missing": "Fichier introuvable : il a été déplacé, renommé ou supprimé depuis l'import.",
        "library.relink_different_file": (
            "Ce fichier ne correspond pas au document importé : son contenu a changé depuis l'import."
        ),
        "library.relink_already_imported": (
            "Ce fichier est déjà dans la bibliothèque, sous « {name} ». Retire ce doublon de la "
            "bibliothèque, puis relance « Localiser »."
        ),
        "library.relink_wrong_kind": (
            "Ce n'est pas le bon type de fichier : un PDF pour un PDF, un fichier de code pour un fichier de code."
        ),
        "library.relink_unreadable": "Ce fichier est illisible.",
        # ── Visite guidée : le document emprunté ──────────────────────────
        # La fiche du document de démonstration est écrite ici plutôt que
        # générée par le LLM : la carte doit être complète immédiatement et
        # hors ligne, et son texte fait partie de ce qu'on montre.
        "onboarding.doc_title": "Comprendre son ordinateur (démonstration)",
        "onboarding.doc_summary": (
            "Extrait de démonstration fourni avec Meta-Capp : le chapitre matériel "
            "d'un rapport d'informatique — processeur, mémoire vive, stockage. Il "
            "sert à montrer la lecture, Clikoda et les sas — il disparaît de la "
            "bibliothèque à la fin de la visite."
        ),
        "onboarding.doc_keywords": "processeur, mémoire vive, stockage, démonstration",
        # ── Langues, méthode feuilleton (services/lang_runs.py) ────────────
        # La question de ressenti de l'au revoir (R8) : l'intitulé et la
        # réponse sont enregistrés tels qu'affichés, comme les réflexions du
        # sas de sortie (nudge_metacog_profile).
        "lang.writing.task.repondre": "Réponds à {speaker} : écris ce que tu lui dirais dans cette scène ({length}).",
        "lang.writing.task.message": "Écris un court message à {speaker} pour lui répondre ({length}).",
        "lang.writing.task.journal": "Tiens ton journal : raconte ta journée ({length}).",
        "lang.writing.task.decrire": "Décris un personnage ou un lieu de l'épisode ({length}).",
        "lang.writing.task.suite": "Imagine la suite de l'épisode ({length}).",
        "lang.writing.task.use": "Emploie si tu peux : {words}.",
        "lang.writing.length.words": "{min} à {max} mots",
        "lang.writing.length.chars": "{min} à {max} caractères",
        "lang.feuilleton.feel.q1": "Comment était cet épisode pour toi ?",
        "lang.feuilleton.feel.q1.a": "Facile",
        "lang.feuilleton.feel.q1.b": "Juste bien",
        "lang.feuilleton.feel.q1.c": "Difficile",
        "lang.feuilleton.feel.q2": "As-tu envie de lire la suite ?",
        "lang.feuilleton.feel.q2.a": "Vivement",
        "lang.feuilleton.feel.q2.b": "Un peu",
        "lang.feuilleton.feel.q2.c": "Pas vraiment",
        "lang.feuilleton.feel.q3": "Qu'as-tu préféré aujourd'hui ?",
        "lang.feuilleton.feel.q3.a": "L'histoire",
        "lang.feuilleton.feel.q3.b": "Le point du jour",
        "lang.feuilleton.feel.q3.c": "Les jeux",
        "lang.feuilleton.feel.q4": "Te sens-tu plus à l'aise qu'en début de semaine ?",
        "lang.feuilleton.feel.q4.a": "Oui",
        "lang.feuilleton.feel.q4.b": "Pareil",
        "lang.feuilleton.feel.q4.c": "Non",
        "lang.feuilleton.feel.q5": "Ton énergie en ce moment ?",
        "lang.feuilleton.feel.q5.a": "En forme",
        "lang.feuilleton.feel.q5.b": "Moyenne",
        "lang.feuilleton.feel.q5.c": "Fatigué·e",
        "lang.feuilleton.feel.q6": "Le point du jour, tu le sens…",
        "lang.feuilleton.feel.q6.a": "Acquis",
        "lang.feuilleton.feel.q6.b": "En cours",
        "lang.feuilleton.feel.q6.c": "Flou",
        # Notes automatiques (déterministes) ajoutées aux notes de l'épisode.
        "lang.feuilleton.note.faux_ami": "Faux-ami : « {form} » — {note}",
        "lang.feuilleton.note.sandhi.tone3": "{hanzi} ({src}) se prononce {dst} devant un autre 3e ton.",
        "lang.feuilleton.note.sandhi.yi": "一 se prononce {dst} ici, à cause du ton de la syllabe suivante.",
        "lang.feuilleton.note.sandhi.bu": "不 se prononce bú devant un 4e ton.",
        "lang.feuilleton.note.component": "Clé {char} ({meaning}) dans {word} : on la retrouve dans {examples}.",
        # ── Erreurs du modèle local (llm/ollama_client) ───────────────────
        # {model} et {ram} : le modèle actif et la RAM que la table lui prête
        # (config/settings.LLM_MODELS) — ce n'est plus « ~16 Go » pour tous.
        "llm.error.memory": "Clikoda ne tient pas dans la mémoire de cet ordinateur : le modèle demande {required} et il n'en reste que {available}. Ferme les applications gourmandes puis réessaie. Avec {model}, Clikoda a besoin d'environ {ram} Go de RAM au total ; un modèle plus léger (Réglages ▸ Clikoda) en demande moins, et le reste de Meta-Capp fonctionne sans elle.",
        "llm.error.memory_generic": "Clikoda ne tient pas dans la mémoire de cet ordinateur. Ferme les applications gourmandes puis réessaie. Avec {model}, Clikoda a besoin d'environ {ram} Go de RAM au total ; un modèle plus léger (Réglages ▸ Clikoda) en demande moins, et le reste de Meta-Capp fonctionne sans elle.",
        # Replis hors-ligne (llm/ollama_client) : ce que l'élève LIT quand Clikoda
        # est muette. C'était du français en dur au milieu du client HTTP — une
        # interface en anglais recevait une accroche française.
        "llm.fallback.chapter": "Chapitre",
        "llm.fallback.hook": "Entre dans {target} en cherchant le lien entre l'idée principale et un exemple concret.",
        "llm.fallback.hook_untitled": "Entre dans ce chapitre en cherchant le lien entre l'idée principale et un exemple concret.",
        "llm.fallback.recap_q1": "Quelle est l'idée principale à retenir ?",
        "llm.fallback.recap_q2": "Quel élément du chapitre dois-tu pouvoir réexpliquer ?",
        "llm.fallback.recap_a2": "La notion centrale, avec ses conditions ou notations importantes.",
        "llm.fallback.recap_q3": "Quel point vérifier avant de continuer ?",
        "llm.fallback.recap_a3": "Vérifier que les définitions et relations utilisées sont comprises.",
    },
    "en": {
        # ── Home ──────────────────────────────────────────────────────────
        "home.subtitle": "Adaptive learning companion",
        # ── App / menu ────────────────────────────────────────────────────
        "menu.file": "File",
        "menu.open_pdf": "Open a document…",
        "menu.library": "Library",
        "menu.settings": "Settings…",
        "desktop.browser_mode": "Meta-Capp is open in your browser: {url}",
        "desktop.browser_not_opened": "The browser did not open by itself: copy the address above into your browser.",
        "desktop.files_readable": "Readable documents",
        "desktop.files_code": "Source code files",
        "desktop.files_all": "All files",
        "desktop.browser_quit": "To quit: \"Quit Meta-Capp\" in the profile menu, or close the tab (automatic stop {minutes} min later), or Ctrl+C here.",
        "menu.view": "View",
        "menu.zoom_in": "Zoom in",
        "menu.zoom_out": "Zoom out",
        "menu.theme_light": "Light theme",
        "menu.theme_dark": "Dark theme",
        "menu.fullscreen": "Full screen",
        "menu.help": "Help",
        "menu.tutorial": "Tutorial",
        "menu.report_issue": "Report a problem",
        "menu.rate": "Rate Meta-Capp",
        "menu.check_updates": "Check for updates…",
        "menu.about": "About",
        # ── Assistant bubble ──────────────────────────────────────────────
        "assistant.mode_changed": "Guidance mode: {mode}",
        "assistant.cancelled": "Request cancelled.",
        # ── Exit screen ───────────────────────────────────────────────────
        "session.reflection_q1": "What is the most important thing you understood in this session?",
        "session.reflection_q2": "Which point is still unclear and deserves another look?",
        "session.reflection_n": "Reflection {n}",
        "assistant.failed": "Clikoda could not handle this request. Please try again.",
        "assistant.mode_discret": "Discreet",
        "assistant.mode_normal": "Normal",
        "assistant.mode_coach": "Coach",
        "assistant.review_toast": "A flashcard is due for review: {front}",
        "assistant.review_action": "Review",
        "assistant.review_done": "Review saved ✓",
        "assistant.flashcard_review_title": "Flashcard to review",
        "assistant.review_reveal": "Show answer",
        "assistant.review_correct": "✓ Knew it",
        "assistant.review_partial": "~ Almost",
        "assistant.review_incorrect": "✗ Forgot",
        "assistant.focus_btn": "🎯 Focus mode",
        "assistant.focus_stop": "🎯 Stop focus",
        "focus.started": "Focus mode: no interventions for {minutes} min. Happy reading!",
        "focus.ended": "Focus over — a short break can help.",
        "focus.stopped": "Focus mode stopped.",
        # ── Fin de chapitre ──────────────────────────────────────────────
        "reader.chapter_done": "Chapter complete 🎉 {title}",
        "reader.chapter_recap_action": "Recap",
        "reader.chapter_recap_loading": "Preparing the recap of \"{title}\"…",
        "reader.next_chapter_tease": "👀 Next chapter — {title}: {hook}",
        # ── Inline Q&A ───────────────────────────────────────────────────
        "qa.mask_placeholder": "temporarily masked answer",
        "qa.low_attention_hint": "Your attention seems low: take a short pause, then come back and answer simply.",
        "qa.criteria_faithful": "Answer faithful to the provided passage.",
        # ── Library: folders ──────────────────────────────────────────────
        "folders.default_name": "New folder",
        "folders.missing": "Folder not found.",
        "folders.parent_missing": "Destination folder not found.",
        "folders.document_missing": "Document not found.",
        "folders.cycle": "A folder cannot be moved into one of its own subfolders.",
        "folders.too_deep": "Folder tree too deep (maximum {n} levels).",
        "brainstorm.missing": "Discussion not found.",
        "brainstorm.folder_missing": "Folder not found.",
        "brainstorm.pin_limit": "At most {n} pinned discussions: unpin one first.",
        "brainstorm.busy": "Clikoda is already answering in this discussion: wait for the reply.",
        "brainstorm.failed": "Clikoda could not process this message. Try again in a moment.",
        "brainstorm.lang.level": "level {level}",
        "brainstorm.lang.program": "programme: point {order} of {size}",
        "brainstorm.lang.last_today": "last session: today",
        "brainstorm.lang.last_days": "last session: {n} d ago",
        "brainstorm.lang.no_study_day": "no study day counted yet",
        "brainstorm.lang.days": "study days: {d7} of the last 7, {d28} of the last 28",
        "brainstorm.lang.minutes": "time spent: ≈ {m} min per study day",
        "brainstorm.lang.episodes": "episodes played: {n}",
        "brainstorm.lang.words": "words met: {seen}, acquired: {acquired}",
        "brainstorm.lang.difficulty": "recent sessions: {detail}",
        "brainstorm.lang.easy": "easy",
        "brainstorm.lang.ok": "right level",
        "brainstorm.lang.hard": "hard",
        "brainstorm.word.entry": "{word} → {translation}",
        "brainstorm.word.acquired": "acquired",
        "brainstorm.word.learning": "not acquired yet",
        "brainstorm.word.met": "met in episode {n}",
        "brainstorm.episode": "episode {n} \"{title}\"",
        "brainstorm.episode.line": "{speaker}: \"{text}\" ({translation})",
        "library.title_empty": "The title cannot be empty.",
        "library.bookmark_page_invalid": "This page does not exist in the document.",
        "annotations.preset.important": "Important",
        "annotations.preset.definition": "Definition",
        "annotations.preset.example": "Example",
        "annotations.preset.review": "To review",
        "annotations.preset.question": "Question",
        "annotations.preset.idea": "Idea",
        "annotations.md.title": "Notes — {title}",
        "annotations.md.bookmark_line": "**Bookmark**: page {page}",
        "annotations.md.signets": "Page markers",
        "annotations.md.page": "Page {page}",
        "annotations.md.sticky": "Sticky note",
        "annotations.md.no_label": "No label",
        "annotations.md.empty": "No notes on this document.",
        "annotations.md.file_suffix": "notes",
        "annotations.md.style.highlight": "highlighted",
        "annotations.md.style.underline": "underlined",
        "annotations.md.style.strike": "struck through",
        "annotations.md.style.outline": "boxed",
        "annotations.error.missing": "This note no longer exists.",
        "annotations.error.color": "Unknown color.",
        "annotations.error.style": "Unknown highlight style.",
        "annotations.error.kind": "Unknown note type.",
        "annotations.error.label_name": "A label name is 1 to {max} characters long.",
        "annotations.error.label_missing": "This label no longer exists.",
        "annotations.error.label_limit": "{max} labels at most.",
        "annotations.error.last_label": "At least one label must remain.",
        "annotations.error.label_order": "The order must list every label, once each.",
        "annotations.error.too_long": "{max} characters at most.",
        "annotations.error.quote": "The highlighted passage is empty or longer than {max} characters.",
        "annotations.error.rects": "Invalid highlight area.",
        "annotations.error.position": "Invalid sticky note position.",
        "library.file_missing": "File not found: it was moved, renamed or deleted since the import.",
        "library.relink_different_file": (
            "This file does not match the imported document: its content has changed since the import."
        ),
        "library.relink_already_imported": (
            "This file is already in the library, as “{name}”. Remove that duplicate from the library, "
            "then try “Locate” again."
        ),
        "library.relink_wrong_kind": "Wrong kind of file: a PDF for a PDF, a code file for a code file.",
        "library.relink_unreadable": "This file cannot be read.",
        # ── Guided tour: the borrowed document ────────────────────────────
        "onboarding.doc_title": "Understanding your computer (demo)",
        "onboarding.doc_summary": (
            "Demo excerpt shipped with Meta-Capp: the hardware chapter of a "
            "computer science report — processor, memory, storage. It exists to "
            "show the reader, Clikoda and the airlocks — it leaves the library when "
            "the tour ends."
        ),
        "onboarding.doc_keywords": "processor, memory, storage, demo",
        # ── Languages, serial method (services/lang_runs.py) ───────────────
        "lang.writing.task.repondre": "Answer {speaker}: write what you would say to them in this scene ({length}).",
        "lang.writing.task.message": "Write a short message to {speaker} in reply ({length}).",
        "lang.writing.task.journal": "Keep your diary: tell about your day ({length}).",
        "lang.writing.task.decrire": "Describe a character or a place from the episode ({length}).",
        "lang.writing.task.suite": "Imagine what happens next in the episode ({length}).",
        "lang.writing.task.use": "Use them if you can: {words}.",
        "lang.writing.length.words": "{min} to {max} words",
        "lang.writing.length.chars": "{min} to {max} characters",
        "lang.feuilleton.feel.q1": "How was this episode for you?",
        "lang.feuilleton.feel.q1.a": "Easy",
        "lang.feuilleton.feel.q1.b": "Just right",
        "lang.feuilleton.feel.q1.c": "Hard",
        "lang.feuilleton.feel.q2": "Do you want to read what happens next?",
        "lang.feuilleton.feel.q2.a": "Can't wait",
        "lang.feuilleton.feel.q2.b": "A little",
        "lang.feuilleton.feel.q2.c": "Not really",
        "lang.feuilleton.feel.q3": "What did you enjoy most today?",
        "lang.feuilleton.feel.q3.a": "The story",
        "lang.feuilleton.feel.q3.b": "Today's point",
        "lang.feuilleton.feel.q3.c": "The games",
        "lang.feuilleton.feel.q4": "Do you feel more at ease than at the start of the week?",
        "lang.feuilleton.feel.q4.a": "Yes",
        "lang.feuilleton.feel.q4.b": "The same",
        "lang.feuilleton.feel.q4.c": "No",
        "lang.feuilleton.feel.q5": "How is your energy right now?",
        "lang.feuilleton.feel.q5.a": "Full of it",
        "lang.feuilleton.feel.q5.b": "Average",
        "lang.feuilleton.feel.q5.c": "Tired",
        "lang.feuilleton.feel.q6": "Today's point feels…",
        "lang.feuilleton.feel.q6.a": "Mastered",
        "lang.feuilleton.feel.q6.b": "On its way",
        "lang.feuilleton.feel.q6.c": "Blurry",
        "lang.feuilleton.note.faux_ami": "False friend: “{form}” — {note}",
        "lang.feuilleton.note.sandhi.tone3": "{hanzi} ({src}) is pronounced {dst} before another third tone.",
        "lang.feuilleton.note.sandhi.yi": "一 is pronounced {dst} here, because of the next syllable's tone.",
        "lang.feuilleton.note.sandhi.bu": "不 is pronounced bú before a fourth tone.",
        "lang.feuilleton.note.component": "Radical {char} ({meaning}) in {word}: you will find it in {examples}.",
        "llm.error.memory": "Clikoda does not fit in this computer's memory: the model needs {required} and only {available} is free. Close memory-hungry applications and try again. With {model}, Clikoda needs about {ram} GB of RAM in total; a lighter model (Settings ▸ Clikoda) needs less, and the rest of Meta-Capp works without it.",
        "llm.error.memory_generic": "Clikoda does not fit in this computer's memory. Close memory-hungry applications and try again. With {model}, Clikoda needs about {ram} GB of RAM in total; a lighter model (Settings ▸ Clikoda) needs less, and the rest of Meta-Capp works without it.",
        "llm.fallback.chapter": "Chapter",
        "llm.fallback.hook": "Step into {target} looking for the link between the main idea and a concrete example.",
        "llm.fallback.hook_untitled": "Step into this chapter looking for the link between the main idea and a concrete example.",
        "llm.fallback.recap_q1": "What is the main idea to remember?",
        "llm.fallback.recap_q2": "Which element of the chapter should you be able to explain again?",
        "llm.fallback.recap_a2": "The central notion, with its important conditions or notations.",
        "llm.fallback.recap_q3": "What should you check before moving on?",
        "llm.fallback.recap_a3": "Check that the definitions and relations used are understood.",
    },
}


def t(key: str, **kwargs) -> str:
    """Return the translated string for *key* in the current language.

    Falls back to French if the key is missing in the active language.
    Applies .format(**kwargs) when keyword arguments are provided.
    """
    val = STRINGS[_lang].get(key) or STRINGS["fr"].get(key, key)
    return val.format(**kwargs) if kwargs else val


def t_in(lang: str, key: str, **kwargs) -> str:
    """Comme `t`, mais dans la langue `lang` plutôt que celle de l'interface :
    ce qui s'adresse à un apprenant de langue suit SA langue d'explication,
    figée dans son profil, même si l'interface a changé depuis."""
    table = STRINGS.get(lang) or STRINGS["fr"]
    val = table.get(key) or STRINGS["fr"].get(key, key)
    return val.format(**kwargs) if kwargs else val


def set_lang(lang: str) -> None:
    global _lang
    if lang not in STRINGS:
        return
    _lang = lang


def current_lang() -> str:
    return _lang
