"""Budget de contexte des prompts du lecteur, en contexte COMPACT.

Le palier minuscule tient 4096 tokens, et le mode économe donne ce même
contexte à toutes les tâches. Or la question, l'évaluation et la réponse libre
en déclarent 6144 à 8192 : mesuré le 2026-10-13 avec le tokenizer de qwen3,
leurs prompts pleins font 5645, 4318 et 4967 tokens sur leurs cas maximaux,
avant même la sortie réservée. Ollama ne refuse pas un prompt trop long — il
en coupe le DÉBUT (le rôle, la page), sans un mot.

Chaque prompt est construit ici sur son cas maximal et estimé avec le
tokenizer du modèle (estimation pessimiste, calibrée sur les vrais
`prompt_eval_count`). Les blocs dont le contenu vient du document ou de
l'étudiant (page, réponse évaluée, passages trouvés ailleurs) sont essayés avec
les contenus les plus coûteux : une page de chinois ou un tableau de chiffres
coûte un token par caractère — c'est pourquoi le contexte compact les borne en
tokens et pas seulement en caractères (config/settings.PromptLimits).

Le contexte PLEIN (modèle de référence, hors mode économe) n'est pas vérifié
ici : ses prompts n'ont pas changé d'un octet, et il reste surveillé après
coup par `ollama_client._warn_if_context_overflow`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import i18n
from config import settings
from config.settings import LLM_MODELS, task_options
from llm import ollama_client, prompts
from llm.prompts import estimate_prompt_tokens
from services import llm_models

LANGS = ["fr", "en"]


def _compact_machines() -> list[tuple]:
    """Chaque (profil, mode économe) dont le contexte de travail est compact."""
    seen: dict = {}
    for profile in LLM_MODELS.values():
        seen.setdefault((profile.tokenizer, profile.max_num_ctx), profile)
    return [
        (profile, economy) for profile in seen.values() for economy in (False, True)
        if economy or profile.max_num_ctx <= settings.ECONOMY_NUM_CTX
    ]


@pytest.fixture(params=_compact_machines(), ids=lambda p: f"{p[0].name}-{'econome' if p[1] else 'normal'}")
def machine(request, monkeypatch):
    profile, economy = request.param
    monkeypatch.setattr(settings, "_active_profile", lambda: profile)
    monkeypatch.setattr(settings, "_economy", lambda: economy)
    monkeypatch.setattr(llm_models, "active_profile", lambda: profile)
    assert settings.compact_context()
    return SimpleNamespace(profile=profile, economy=economy, tokenizer=profile.tokenizer)


@pytest.fixture(params=LANGS)
def lang(request):
    previous = i18n.current_lang()
    i18n.set_lang(request.param)
    yield request.param
    i18n.set_lang(previous)


FR = ("La descente de gradient stochastique met à jour les paramètres dans la direction opposée au gradient "
      "de la fonction de perte, estimé sur un mini-lot tiré au hasard ; le taux d'apprentissage règle le pas. ")
LONG = FR * 20
# Les contenus les plus coûteux d'une page : prose, chinois, tableau de chiffres.
PAGES = {
    "prose": LONG,
    "chinois": "梯度下降法沿着损失函数梯度的反方向更新参数，学习率决定步长。" * 120,
    "chiffres": "\n".join(f"{i:03d} | 0.{i:04d} | {i * 1.25:8.3f} | {i * 7:06d}" for i in range(400)),
}
PROFILE = {"user_id": 1, "context_comprehension": 31.25, "creativity": 48.5, "retention": 55.75,
           "curiosity": 72.0, "meta_cognition": 34.25, "attention": 38.5, "sessions_count": 142,
           "updated_at": "2026-10-13 21:00:00"}
GAUGES = {key: 37.3 for key in ("attention", "context_comprehension", "creativity", "retention",
                                "curiosity", "meta_cognition")}
HISTORY = [{"question": LONG[:240], "question_type": "comprehension", "answer": LONG[:240], "verdict": "partial"}] * 5
STRUGGLES = [{"question": LONG[:120], "chapter_title": "Chapitre 3 — Optimisation", "fail_count": 3}] * 3
QUOTES = [LONG[:200]] * 5


def _passages(page_kind: str) -> list[dict]:
    """Six passages de la longueur maximale, dont une table de chiffres."""
    table = {"page": 5, "table": True, "text": PAGES["chiffres"][:2000]}
    prose = {"page": 12, "table": False, "text": PAGES[page_kind][:900]}
    return [table] + [prose] * 5


def _check(task: str, prompt: str, lang: str, machine) -> None:
    options = task_options(task)
    system = estimate_prompt_tokens(prompts.build_system_prompt(lang), machine.tokenizer)
    used = system + estimate_prompt_tokens(prompt, machine.tokenizer) + options["num_predict"]
    assert used <= options["num_ctx"], (
        f"{task} ({lang}, {machine.profile.name}{', économe' if machine.economy else ''}) : "
        f"{used} tokens estimés > num_ctx {options['num_ctx']}"
    )


@pytest.mark.parametrize("page_kind", list(PAGES))
def test_answer_prompt_fits(machine, lang, page_kind):
    prompt = prompts.build_assistant_answer_prompt(
        page_text=PAGES[page_kind], user_question=LONG[:500], doc_title="Un titre de document assez long.pdf",
        chapter_title="Chapitre 4 — Méthodes du premier ordre", page_number=127, metacog_profile=PROFILE,
        session_gauges=GAUGES, recent_exchanges=[{"question": LONG[:160], "answer": LONG[:200]}] * 6,
        related_flashcards=[{"front": LONG[:100]}] * 3, selected_snippets=QUOTES, user_highlights=QUOTES,
        retrieved_passages=_passages(page_kind), whole_document_search=True,
    )
    _check("assistant_answer", prompt, lang, machine)


@pytest.mark.parametrize("page_kind", list(PAGES))
def test_question_prompt_fits(machine, lang, page_kind):
    prompt = prompts.build_question_prompt(
        paragraph=PAGES[page_kind], chapter_title="Chapitre 4 — Méthodes du premier ordre", doc_title="Un titre.pdf",
        metacog_profile=PROFILE, history=HISTORY, session_gauges=GAUGES,
        recent_question_types=["comprehension", "application", "connection", "recall", "metacognition"],
        standalone=True, past_struggles=STRUGGLES, user_highlights=QUOTES,
    )
    _check("question", prompt, lang, machine)


@pytest.mark.parametrize("page_kind", list(PAGES))
def test_evaluation_prompt_fits(machine, lang, page_kind):
    prompt = prompts.build_evaluation_prompt(
        question={"question": LONG[:300], "question_type": "open", "expected_answer": LONG[:400],
                  "choices": ["choix " + LONG[:60]] * 4},
        user_answer=PAGES[page_kind][:3000], paragraph=PAGES[page_kind], metacog_profile=PROFILE,
        history=HISTORY, past_struggles=STRUGGLES,
    )
    _check("evaluation", prompt, lang, machine)


@pytest.mark.parametrize("page_kind", list(PAGES))
def test_page_commands_fit(machine, lang, page_kind):
    """Reformuler, résumer, accrocher : leur fenêtre n'est pas plus petite en
    contexte compact (4096, voire davantage en mode économe), mais le tokenizer
    de qwen3 compte plus cher."""
    _check("rephrasing", prompts.build_rephrasing_prompt(PAGES[page_kind], 3), lang, machine)
    _check("curiosity_hook", prompts.build_curiosity_hook_prompt(
        doc_title="Un titre.pdf", chapter_title="Chapitre 4", subchapter_title="",
        chapter_excerpt=PAGES[page_kind][:1500], profile=PROFILE,
    ), lang, machine)
    _check("chapter_summary", prompts.build_chapter_summary_prompt(
        chapter_title="Chapitre 4", paragraphs_summary=[PAGES[page_kind][:1500]], metacog_profile=PROFILE,
    ), lang, machine)


# ── Ce que le prompt compact garde, et ce qu'il ne dit plus ─────────────────


def test_no_prompt_claims_an_image_the_model_cannot_see(monkeypatch, lang):
    """Le palier minuscule ne lit pas les images : `ollama_client` les écarte
    avant l'appel, et un petit modèle à qui l'on dit « une image est jointe »
    en invente le contenu."""
    tiny = LLM_MODELS["qwen3:1.7b"]
    monkeypatch.setattr(settings, "_active_profile", lambda: tiny)
    monkeypatch.setattr(llm_models, "active_profile", lambda: tiny)
    built = [
        prompts.build_question_prompt(paragraph=FR, standalone=True),
        prompts.build_evaluation_prompt(question={"question": "Q ?"}, user_answer="R.", paragraph=FR),
        prompts.build_rephrasing_prompt(FR, 0),
    ]
    for prompt in built:
        assert "image est jointe" not in prompt and "image is attached" not in prompt.replace("If an image", "")
        assert "image de la page est jointe" not in prompt and "image of the page is attached" not in prompt


def test_the_reference_model_still_reads_the_image_rules(lang):
    assert not settings.compact_context()
    prompt = prompts.build_question_prompt(paragraph=FR, standalone=True)
    assert ("Une image est jointe" in prompt) or ("An image is attached" in prompt)


def test_the_compact_question_keeps_what_the_offline_fallback_reads(machine, lang):
    """Même schéma JSON que le prompt plein, donc le même parseur ; et les
    intitulés que le repli local relit (paragraphe, type cible, seuil
    d'attention) : sans eux, Ollama éteint, la question repliée ne citerait
    plus rien du paragraphe."""
    gauges = dict(GAUGES, attention=20.0)
    compact = prompts.build_question_prompt(paragraph=LONG, metacog_profile=PROFILE, session_gauges=gauges,
                                            standalone=True)
    fallback = ollama_client._fallback_question_from_prompt(compact)
    assert fallback and fallback.get("question")
    assert fallback.get("session_hint")  # le seuil d'attention a été relu
    assert '"question_type"' in compact and '"paragraph_mask"' in compact and '"source_excerpt"' in compact


def test_the_compact_question_is_a_fraction_of_the_full_one(monkeypatch):
    full = prompts.build_question_prompt(paragraph=FR, standalone=True)
    tiny = LLM_MODELS["qwen3:1.7b"]
    monkeypatch.setattr(settings, "_active_profile", lambda: tiny)
    monkeypatch.setattr(llm_models, "active_profile", lambda: tiny)
    compact = prompts.build_question_prompt(paragraph=FR, standalone=True)
    assert estimate_prompt_tokens(compact, "qwen") * 3 < estimate_prompt_tokens(full, "qwen")


@pytest.mark.parametrize("task", ["question", "evaluation", "assistant_answer", "rephrasing"])
def test_a_page_is_cut_in_tokens_not_only_in_characters(machine, task):
    """2000 caractères de chinois coûtent 2000 tokens : la borne en caractères
    seule laissait passer trois fois le budget d'une page de français."""
    lim = settings.prompt_limits()
    budget = lim.page_tokens[task]
    excerpt = prompts._page_excerpt(PAGES["chinois"], lim, task)
    assert estimate_prompt_tokens(excerpt, machine.tokenizer) <= budget
    assert len(excerpt) < lim.page_chars


def test_a_token_cut_falls_between_two_words(machine):
    cut = prompts._fit_tokens(LONG, 100)
    assert estimate_prompt_tokens(cut, machine.tokenizer) <= 100
    assert LONG.startswith(cut) and LONG[len(cut)] == " "
