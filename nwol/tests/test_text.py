# Tests de utils/text.document_reference : un texte qui ne se comprend qu'avec
# le document sous les yeux (« according to the text », « Table 3.5 »).
import pytest

from utils.text import document_reference

# Cartes automatiques réelles, créées pendant des lectures puis servies seules
# dans le sas d'entrée — c'est ce qu'elles font que le détecteur doit attraper.
REAL_CARDS = (
    "What is the conceptual progression of the research, starting from initial classification "
    "tasks and ending with abdominal organ segmentation, according to the document?",
    "When does transfer learning fail, according to the text, even when the source organ is the "
    "closest possible organ to the target?",
    "Based on Table 3.5, which algorithm achieved the best balance between stability and "
    "performance on the test organ?",
    "Quels sont les quatre biais de protocole mentionnés dans le texte qui gonflent le score "
    "rapporté ?",
)


@pytest.mark.parametrize("text", REAL_CARDS)
def test_real_cards_that_need_the_document_are_caught(text):
    assert document_reference(text) is not None


@pytest.mark.parametrize("text, expected", [
    ("…according to the document?", "according to the document"),
    ("Based on Table 3.5, which algorithm…", "table 3"),
    ("Quels biais sont mentionnés dans le texte ?", "mentionnes dans le texte"),
    ("D’après le texte, pourquoi ?", "d'apres le texte"),
    ("In Table I, which configuration…", "table i"),
])
def test_the_reference_found_is_returned_folded(text, expected):
    assert document_reference(text) == expected


@pytest.mark.parametrize("text", [
    # le document lui-même
    "Selon le passage, que se passe-t-il ?",
    "Dans ce passage, l'auteur défend quelle idée ?",
    "Dans le passage, quel est le rôle de X ?",
    "D'après le paragraphe, qui parle ?",
    "Selon l'auteur, la liberté est-elle innée ?",
    "Que dit le texte sur la liberté ?",
    "Quel est le titre du document ?",
    "Which loss function is used in the paper?",
    "What does the author argue?",
    "What is the main idea of the passage?",
    "In this chapter, what is introduced?",
    "In the text, what does X refer to?",
    # une numérotation du document
    "Que montre la figure 2 ?",
    "Équation (4) : que vaut x ?",
    "Que contient le tableau n° 3 ?",
    "See Appendix A for the proof.",
    "What is shown on page 4?",
    # un déictique
    "Que représente cette figure ?",
    "Que montre ce schéma ?",
    "Que lit-on sur la figure ?",
    "Que voit-on dans le tableau ?",
    "Que dit le tableau ci-dessus ?",
    "Using the figure above, estimate y.",
    "What does the table below show?",
    "Based on the following table, what is the mean?",
    "As shown above, which property holds?",
])
def test_references_to_the_document_are_caught(text):
    assert document_reference(text) is not None


@pytest.mark.parametrize("text", [
    "What is a hash table?",
    "Récite la table de multiplication de 7.",
    "Qu'est-ce qu'une figure de style ?",
    "L'eau bout au-dessus de 100 °C.",
    "Que vaut $u_n$ quand n tend vers l'infini ?",
    "Où se trouve le fer dans le tableau périodique ?",
    "Que se passe-t-il dans le passage de l'état liquide à l'état gazeux ?",
    "Justifier le passage à la limite.",
    "Où placer la balise title dans le document HTML ?",
    "Selon l'article 1er de la DDHC, les hommes naissent libres et égaux.",
    "According to the periodic table, what is the symbol of iron?",
    "What is the text of the First Amendment?",
    "How do you open a text file in Python?",
    "Based on the graph structure, which algorithm fits?",
    "Where is the graph above the x-axis?",
    "Temperatures below 0 °C freeze water.",
    # le contenu annoncé suit, dans la carte même
    "Sort the following list: 5, 3, 8.",
    "Résous l'équation ci-dessous : x + 1 = 2",
    # anaphore : le nom est posé avant d'être repris
    "Soit un tableau t de n entiers. Comment trier ce tableau ?",
    "Consider the list [3, 1, 2]. What is the list above once sorted?",
    # cartes de langue
    "Bonjour en turc",
    "Comment vas-tu ? en turc",
    "",
])
def test_self_contained_texts_are_left_alone(text):
    assert document_reference(text) is None


def test_no_static_quiz_question_is_mistaken_for_a_reference():
    """Le catalogue statique se répond sans document : aucune question ni
    proposition ne doit être prise pour un renvoi (le quiz l'écarterait)."""
    from db.quiz_questions import _STATIC_QUESTIONS

    flagged = [
        q["question"] for q in _STATIC_QUESTIONS
        if document_reference(q["question"])
        or any(document_reference(str(c)) for c in q.get("choices") or [])
    ]
    assert flagged == []


def test_quiz_drops_a_question_that_needs_its_missing_context():
    """Le quiz partage les patrons : une question qui renvoie au document n'est
    servie qu'avec son contexte de lecture."""
    from db.quiz_questions import _is_unusable_for_quiz

    question = "When does transfer learning fail, according to the text?"
    assert _is_unusable_for_quiz(question, source_context=None)
    assert not _is_unusable_for_quiz(question, source_context="Transfer learning fails when…")
    assert not _is_unusable_for_quiz("What is transfer learning?", source_context=None)
