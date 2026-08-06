import type { Lang } from "../../i18n";

export interface ScienceCard {
  title: string;
  body: string;
  user?: string;
  system?: string;
}

export interface ScienceSection {
  id: string;
  title: string;
  intro?: string;
  cards: ScienceCard[];
}

export interface ScienceReference {
  authors: string;
  detail: string;
  doi?: string;
}

export interface ScienceContent {
  title: string;
  intro: string[];
  definition: ScienceCard;
  flowTitle: string;
  flowIntro: string;
  flowSteps: string[];
  sections: ScienceSection[];
  referencesTitle: string;
  referencesIntro: string;
  references: ScienceReference[];
}

export interface WhyContent {
  title: string;
  principle: string;
  conclusion: string;
  inApp: string;
  sources: string[];
}

export type WhyKey = "entry" | "warmup" | "exit" | "postExitRest";

const referencesFr: ScienceReference[] = [
  {
    authors: "Flavell, J. H. (1979)",
    detail:
      "Metacognition and Cognitive Monitoring: A New Area of Cognitive-Developmental Inquiry. American Psychologist, 34(10), 906-911.",
    doi: "10.1037/0003-066X.34.10.906",
  },
  {
    authors: "Dunlosky, J., & Metcalfe, J. (2009)",
    detail:
      "Metacognition. SAGE Publications. Ouvrage de synthèse sur le monitoring, le contrôle des stratégies et les jugements métacognitifs.",
  },
  {
    authors: "Zimmerman, B. J. (2002)",
    detail: "Becoming a Self-Regulated Learner: An Overview. Theory Into Practice, 41(2), 64-70.",
    doi: "10.1207/s15430421tip4102_2",
  },
  {
    authors: "Hattie, J., & Timperley, H. (2007)",
    detail: "The Power of Feedback. Review of Educational Research, 77(1), 81-112.",
    doi: "10.3102/003465430298487",
  },
  {
    authors: "Roediger, H. L., & Karpicke, J. D. (2006)",
    detail: "Test-Enhanced Learning: Taking Memory Tests Improves Long-Term Retention. Psychological Science, 17(3), 249-255.",
    doi: "10.1111/j.1467-9280.2006.01693.x",
  },
  {
    authors: "Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013)",
    detail: "Improving Students' Learning With Effective Learning Techniques. Psychological Science in the Public Interest, 14(1), 4-58.",
    doi: "10.1177/1529100612453266",
  },
  {
    authors: "Ebbinghaus, H. (1885/1913)",
    detail: "Memory: A Contribution to Experimental Psychology. Travaux fondateurs sur la courbe de l'oubli et l'économie de réapprentissage.",
  },
  {
    authors: "Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006)",
    detail: "Distributed Practice in Verbal Recall Tasks: A Review and Quantitative Synthesis. Psychological Bulletin, 132(3), 354-380.",
    doi: "10.1037/0033-2909.132.3.354",
  },
  {
    authors: "Leitner, S. (1972/1973)",
    detail: "So lernt man lernen. Méthode pratique de boîte à fiches fondée sur la répétition espacée et le rappel actif.",
  },
  {
    authors: "Kornell, N., & Bjork, R. A. (2008)",
    detail: "Learning Concepts and Categories: Is Spacing the Enemy of Induction? Psychological Science, 19(6), 585-592.",
    doi: "10.1111/j.1467-9280.2008.02127.x",
  },
  {
    authors: "Taylor, K., & Rohrer, D. (2010)",
    detail: "The Effects of Interleaved Practice. Applied Cognitive Psychology, 24(6), 837-848.",
    doi: "10.1002/acp.1598",
  },
  {
    authors: "Bjork, E. L., & Bjork, R. A. (2011)",
    detail: "Making Things Hard on Yourself, but in a Good Way: Creating Desirable Difficulties to Enhance Learning. In Psychology and the Real World.",
  },
  {
    authors: "Kang, M. J., Hsu, M., Krajbich, I. M., et al. (2009)",
    detail:
      "The Wick in the Candle of Learning: Epistemic Curiosity Activates Reward Circuitry and Enhances Memory. Psychological Science, 20(8), 963-973.",
    doi: "10.1111/j.1467-9280.2009.02402.x",
  },
  {
    authors: "Feynman, R. P. (1985)",
    detail: "Surely You're Joking, Mr. Feynman! Référence culturelle utilisée ici comme heuristique de questionnement actif, pas comme preuve expérimentale isolée.",
  },
  {
    authors: "Chi, M. T. H., de Leeuw, N., Chiu, M.-H., & LaVancher, C. (1994)",
    detail: "Eliciting Self-Explanations Improves Understanding. Cognitive Science, 18(3), 439-477.",
    doi: "10.1207/s15516709cog1803_3",
  },
  {
    authors: "Loewenstein, G. (1994)",
    detail: "The Psychology of Curiosity: A Review and Reinterpretation. Psychological Bulletin, 116(1), 75-98.",
    doi: "10.1037/0033-2909.116.1.75",
  },
  {
    authors: "Ainsworth, S. (2006)",
    detail: "DeFT: A Conceptual Framework for Considering Learning with Multiple Representations. Learning and Instruction, 16(3), 183-198.",
    doi: "10.1016/j.learninstruc.2006.03.001",
  },
  {
    authors: "Dewar, M., Alber, J., Butler, C., Cowan, N., & Della Sala, S. (2012)",
    detail:
      "Brief Wakeful Resting Boosts New Memories Over the Long Term. Psychological Science, 23(9), 955-960. Travaux menés notamment à l'Université d'Édimbourg.",
    doi: "10.1177/0956797612441220",
  },
];

const referencesEn: ScienceReference[] = [
  {
    authors: "Flavell, J. H. (1979)",
    detail:
      "Metacognition and Cognitive Monitoring: A New Area of Cognitive-Developmental Inquiry. American Psychologist, 34(10), 906-911.",
    doi: "10.1037/0003-066X.34.10.906",
  },
  {
    authors: "Dunlosky, J., & Metcalfe, J. (2009)",
    detail: "Metacognition. SAGE Publications. A comprehensive overview of monitoring, strategy control and metacognitive judgements.",
  },
  {
    authors: "Zimmerman, B. J. (2002)",
    detail: "Becoming a Self-Regulated Learner: An Overview. Theory Into Practice, 41(2), 64-70.",
    doi: "10.1207/s15430421tip4102_2",
  },
  {
    authors: "Hattie, J., & Timperley, H. (2007)",
    detail: "The Power of Feedback. Review of Educational Research, 77(1), 81-112.",
    doi: "10.3102/003465430298487",
  },
  {
    authors: "Roediger, H. L., & Karpicke, J. D. (2006)",
    detail: "Test-Enhanced Learning: Taking Memory Tests Improves Long-Term Retention. Psychological Science, 17(3), 249-255.",
    doi: "10.1111/j.1467-9280.2006.01693.x",
  },
  {
    authors: "Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013)",
    detail: "Improving Students' Learning With Effective Learning Techniques. Psychological Science in the Public Interest, 14(1), 4-58.",
    doi: "10.1177/1529100612453266",
  },
  {
    authors: "Ebbinghaus, H. (1885/1913)",
    detail: "Memory: A Contribution to Experimental Psychology. Foundational work on the forgetting curve and the savings method.",
  },
  {
    authors: "Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006)",
    detail: "Distributed Practice in Verbal Recall Tasks: A Review and Quantitative Synthesis. Psychological Bulletin, 132(3), 354-380.",
    doi: "10.1037/0033-2909.132.3.354",
  },
  {
    authors: "Leitner, S. (1972/1973)",
    detail: "So lernt man lernen. A practical flashcard method based on spaced repetition and active recall.",
  },
  {
    authors: "Kornell, N., & Bjork, R. A. (2008)",
    detail: "Learning Concepts and Categories: Is Spacing the Enemy of Induction? Psychological Science, 19(6), 585-592.",
    doi: "10.1111/j.1467-9280.2008.02127.x",
  },
  {
    authors: "Taylor, K., & Rohrer, D. (2010)",
    detail: "The Effects of Interleaved Practice. Applied Cognitive Psychology, 24(6), 837-848.",
    doi: "10.1002/acp.1598",
  },
  {
    authors: "Bjork, E. L., & Bjork, R. A. (2011)",
    detail: "Making Things Hard on Yourself, but in a Good Way: Creating Desirable Difficulties to Enhance Learning. In Psychology and the Real World.",
  },
  {
    authors: "Kang, M. J., Hsu, M., Krajbich, I. M., et al. (2009)",
    detail:
      "The Wick in the Candle of Learning: Epistemic Curiosity Activates Reward Circuitry and Enhances Memory. Psychological Science, 20(8), 963-973.",
    doi: "10.1111/j.1467-9280.2009.02402.x",
  },
  {
    authors: "Feynman, R. P. (1985)",
    detail: "Surely You're Joking, Mr. Feynman! Used here as a cultural heuristic for active questioning, not as isolated experimental evidence.",
  },
  {
    authors: "Chi, M. T. H., de Leeuw, N., Chiu, M.-H., & LaVancher, C. (1994)",
    detail: "Eliciting Self-Explanations Improves Understanding. Cognitive Science, 18(3), 439-477.",
    doi: "10.1207/s15516709cog1803_3",
  },
  {
    authors: "Loewenstein, G. (1994)",
    detail: "The Psychology of Curiosity: A Review and Reinterpretation. Psychological Bulletin, 116(1), 75-98.",
    doi: "10.1037/0033-2909.116.1.75",
  },
  {
    authors: "Ainsworth, S. (2006)",
    detail: "DeFT: A Conceptual Framework for Considering Learning with Multiple Representations. Learning and Instruction, 16(3), 183-198.",
    doi: "10.1016/j.learninstruc.2006.03.001",
  },
  {
    authors: "Dewar, M., Alber, J., Butler, C., Cowan, N., & Della Sala, S. (2012)",
    detail:
      "Brief Wakeful Resting Boosts New Memories Over the Long Term. Psychological Science, 23(9), 955-960. Work led in part at the University of Edinburgh.",
    doi: "10.1177/0956797612441220",
  },
];

export const scienceContent: Record<Lang, ScienceContent> = {
  fr: {
    title: "Pourquoi Meta-Capp fonctionne comme ça ?",
    intro: [
      "Cette page transpose dans la version web la page explicative qui existait déjà dans l'application Tkinter. Elle liste les sources psychologiques utilisées pour justifier les sas, les questions, les flashcards, les jauges et le profil métacognitif.",
      "Les jauges ne sont pas des mesures médicales. Ce sont des indicateurs pédagogiques internes qui résument des signaux observables pour adapter le rythme, les questions et les révisions.",
      "La version web garde le principe central : lire librement, interagir avec Gemma, produire des réponses, recevoir du feedback, consolider le profil, puis terminer par un sas de réflexion et une pause de repos.",
    ],
    definition: {
      title: "Définition simple",
      body:
        "Dans le modèle fondateur de Flavell, l'apprenant ne fait pas seulement une tâche : il surveille aussi son activité mentale. Il peut repérer une confusion, estimer son niveau de certitude, choisir de relire, demander un exemple, changer de stratégie ou s'arrêter pour réfléchir. Dans Meta-Capp, cette idée devient une boucle : question, réponse, feedback, jauges, adaptation, réflexion de fin de session.",
    },
    flowTitle: "Flux web actuel",
    flowIntro:
      "Le schéma Tkinter historique dépendait d'assets générés. La version web garde ici un schéma textuel stable, fidèle au lecteur scroll libre actuel.",
    flowSteps: [
      "Sas d'entrée : ralentir, poser l'attention, recevoir une accroche de curiosité.",
      "Warm-up : revoir les cartes dues avant d'ajouter de nouvelles informations.",
      "Lecture libre : parcourir le PDF en scroll, avec Gemma connectée à la page visible.",
      "Questions et feedback : questions libres, Q&R guidée, verdicts et surlignages.",
      "Profil : jauges live, historique, flashcards et courbes de progression.",
      "Sas de sortie : métriques, réflexion métacognitive, finalisation de session.",
      "Repos final : une courte pause sans stimulation nouvelle pour laisser consolider.",
    ],
    sections: [
      {
        id: "software",
        title: "Fonctionnement concret du logiciel",
        cards: [
          {
            title: "Lecture scroll libre",
            body: "Le document reste entier et scrollable. La page dominante visible donne le contexte envoyé à Gemma, au lieu d'un flux Tkinter bloqué paragraphe par paragraphe.",
            user: "L'utilisateur lit naturellement, zoome et scrolle sans progression verrouillée.",
            system: "Le système suit page visible, dwell time, visites, échanges récents et session active.",
          },
          {
            title: "Assistant Gemma",
            body: "Gemma répond aux questions, reformule, résume la page courante, génère des accroches et peut lancer une question guidée.",
            user: "Une bulle déplaçable accompagne la lecture.",
            system: "Les réponses libres peuvent mettre à jour les jauges live et les échanges sont persistés.",
          },
          {
            title: "Questions adaptatives",
            body: "Les questions peuvent viser compréhension, application, curiosité, visualisation, métacognition ou anticipation. Le web utilise surtout la page visible, le profil, les jauges live et les difficultés passées.",
            user: "La question arrive dans le contexte de la page lue.",
            system: "La question et la réponse guidée sont persistées dans les tables pédagogiques.",
          },
          {
            title: "Feedback immédiat",
            body: "La réponse est évaluée avec un verdict correct, partiel ou incorrect, puis un feedback. Le but n'est pas seulement de noter, mais de corriger la stratégie.",
            user: "L'étudiant sait ce qui est correct et ce qui doit être repris.",
            system: "Les verdicts alimentent les jauges live, les historiques et les difficultés récurrentes.",
          },
          {
            title: "Flashcards",
            body: "Les cartes prolongent le rappel actif après la lecture. Elles peuvent être révisées hors session ou au début d'une nouvelle session du même document.",
            user: "Une carte recto-verso transforme une réponse utile en matière à réviser.",
            system: "La date de révision, le document et la difficulté guident le warm-up.",
          },
          {
            title: "Sas de sortie",
            body: "Le bilan web enregistre les réflexions et consolide le profil depuis les jauges live ou, en repli, depuis les métriques de réussite.",
            user: "La session se termine par quelques réponses personnelles.",
            system: "Les réflexions sont stockées et le profil durable est nudgé en fin de session.",
          },
        ],
      },
      {
        id: "gauges",
        title: "Ce que les jauges veulent dire",
        intro: "Ces critères sont des repères pédagogiques, pas des diagnostics.",
        cards: [
          { title: "Attention", body: "Engagement dans la tâche, stabilité de lecture et capacité à aller au bout d'une réponse." },
          { title: "Compréhension du contexte", body: "Capacité à répondre en s'appuyant sur le bon passage plutôt qu'en devinant hors sujet." },
          { title: "Créativité", body: "Capacité à produire une analogie, un exemple ou un lien personnel utile." },
          { title: "Rétention", body: "Capacité à rappeler l'information activement, notamment dans les quiz et flashcards." },
          { title: "Curiosité", body: "Capacité à formuler des questions ou liens qui prolongent le cours sans s'éparpiller." },
          { title: "Métacognition", body: "Capacité à nommer ses blocages, choisir une stratégie et définir une prochaine action." },
        ],
      },
      {
        id: "science",
        title: "Expériences et résultats scientifiques utilisés",
        cards: [
          {
            title: "Monitoring et contrôle métacognitif",
            body: "Flavell puis Dunlosky & Metcalfe décrivent la métacognition comme un couple monitoring/contrôle : observer sa compréhension, puis agir sur sa stratégie. Meta-Capp reprend cela avec les jauges, les questions d'anticipation et les questions de réflexion.",
          },
          {
            title: "Auto-régulation de l'apprentissage",
            body: "Zimmerman présente l'apprentissage auto-régulé comme un cycle : préparation, action contrôlée, puis auto-réflexion. Les sas d'entrée et de sortie encadrent précisément ce cycle.",
          },
          {
            title: "Retrieval practice",
            body: "Roediger & Karpicke montrent que se tester ne sert pas seulement à mesurer la mémoire : le rappel actif améliore la rétention à long terme. C'est la raison des questions guidées et des flashcards.",
          },
          {
            title: "Feedback formatif",
            body: "Hattie & Timperley montrent qu'un feedback utile indique ce qui est atteint, ce qui manque et quelle action faire ensuite. Meta-Capp traduit cela en verdicts, compléments, indices et reformulations.",
          },
          {
            title: "Auto-explication",
            body: "Chi et ses collègues ont montré que demander à l'élève d'expliquer avec ses mots peut améliorer la compréhension. Les réponses ouvertes et les reformulations exploitent ce principe.",
          },
          {
            title: "Curiosité et écart de connaissance",
            body: "Loewenstein décrit la curiosité comme liée à l'écart entre ce que l'on sait et ce que l'on veut comprendre. Kang et al. montrent que la curiosité épistémique active des circuits de récompense et peut améliorer le rappel ultérieur.",
          },
          {
            title: "Visualisation et représentations multiples",
            body: "Ainsworth montre que plusieurs représentations peuvent aider l'apprentissage si elles servent une tâche cognitive claire. Les questions de visualisation sont donc pertinentes face aux figures, mécanismes ou relations spatiales.",
          },
          {
            title: "Repos éveillé après apprentissage",
            body: "Dewar et al., à l'Université d'Édimbourg, ont comparé un repos éveillé de 10 minutes après apprentissage verbal à une tâche de différence visuelle. Le repos a amélioré le rappel après 15-30 minutes et encore après 7 jours. Le sas de repos final en garde une version courte et non intrusive.",
          },
        ],
      },
      {
        id: "memory",
        title: "Méthodes d'apprentissage ajoutées dans la page",
        intro:
          "Ces méthodes rendent la métacognition actionnable : l'étudiant ne se contente pas de lire, il vérifie, récupère, espace, mélange, explique et relie ce qu'il apprend à ses propres questions.",
        cards: [
          {
            title: "Pourquoi la relecture passive est insuffisante",
            body: "Relire donne souvent une impression de familiarité, mais cela ne prouve pas que l'information peut être rappelée sans support. Meta-Capp demande donc de produire des réponses.",
          },
          {
            title: "Récupération active",
            body: "Faire revenir l'information depuis la mémoire est plus difficile qu'une relecture, mais cette difficulté consolide la trace et révèle les lacunes.",
          },
          {
            title: "Répétition espacée",
            body: "Ebbinghaus décrit la fragilité de la mémoire avec le temps ; Cepeda et al. montrent l'intérêt de distribuer la pratique. Les flashcards utilisent cet oubli comme signal de révision.",
          },
          {
            title: "Système de Leitner",
            body: "Une carte réussie revient moins vite, une carte ratée revient plus tôt. Le principe utile est simple : réussite, hésitation et oubli guident la prochaine révision.",
          },
          {
            title: "Interleaving",
            body: "Mélanger des types proches force à choisir la bonne stratégie au lieu d'appliquer un réflexe. Meta-Capp varie donc les types de questions.",
          },
          {
            title: "Difficultés désirables",
            body: "Bjork & Bjork décrivent des difficultés qui ralentissent l'impression de facilité mais renforcent l'apprentissage : rappel actif, espacement, variation et auto-explication.",
          },
          {
            title: "Amorçage par la curiosité",
            body: "Une question intrigante crée un écart cognitif. L'accroche du sas d'entrée sert à entrer dans la session avec une attente active plutôt qu'une lecture passive.",
          },
          {
            title: "Pause de consolidation",
            body: "Le repos éveillé post-apprentissage réduit l'interférence immédiate. Meta-Capp l'adapte en une minute sans nouvelle stimulation après le bilan.",
          },
          {
            title: "Méthode Feynman et questions personnelles",
            body: "Expliquer simplement, repérer les zones floues, revenir à la source puis réexpliquer aide à transformer la compréhension vague en modèle manipulable.",
          },
        ],
      },
    ],
    referencesTitle: "Sources scientifiques",
    referencesIntro: "Références reprises de la page Tkinter existante, avec l'ajout explicite du repos éveillé de Dewar et al.",
    references: referencesFr,
  },
  en: {
    title: "Why does Meta-Capp work this way?",
    intro: [
      "This page ports to the web the explanatory page that already existed in the Tkinter application. It lists the psychological sources used to justify the airlocks, questions, flashcards, gauges and metacognitive profile.",
      "The gauges are not medical measures. They are internal pedagogical indicators that summarize observable signals to adapt pacing, questions and reviews.",
      "The web version keeps the central idea: read freely, interact with Gemma, produce answers, receive feedback, consolidate the profile, then close with reflection and a short rest pause.",
    ],
    definition: {
      title: "Simple definition",
      body:
        "In Flavell's foundational model, the learner does not just perform a task: they also monitor their own mental activity. They can notice confusion, estimate certainty, choose to re-read, ask for an example, change strategy or pause to reflect. In Meta-Capp, this becomes a loop: question, answer, feedback, gauges, adaptation, end-of-session reflection.",
    },
    flowTitle: "Current web flow",
    flowIntro:
      "The historical Tkinter diagram depended on generated assets. The web version uses a stable textual diagram faithful to the current free-scroll reader.",
    flowSteps: [
      "Entry airlock: slow down, settle attention, receive a curiosity hook.",
      "Warm-up: review due cards before adding new information.",
      "Free reading: scroll through the PDF, with Gemma connected to the visible page.",
      "Questions and feedback: free questions, guided Q&A, verdicts and highlights.",
      "Profile: live gauges, history, flashcards and progress curves.",
      "Exit airlock: metrics, metacognitive reflection, session finalization.",
      "Final rest: a short pause without new stimulation to let learning consolidate.",
    ],
    sections: [
      {
        id: "software",
        title: "How the software works",
        cards: [
          {
            title: "Free-scroll reading",
            body: "The document stays whole and scrollable. The dominant visible page gives Gemma its context instead of a Tkinter paragraph-by-paragraph gated flow.",
            user: "The user reads naturally, zooms and scrolls without a locked progression.",
            system: "The system tracks visible page, dwell time, visits, recent exchanges and the active session.",
          },
          {
            title: "Gemma assistant",
            body: "Gemma answers questions, rephrases, summarizes the current page, generates curiosity hooks and can start a guided question.",
            user: "A draggable bubble accompanies reading.",
            system: "Free answers can update live gauges and exchanges are persisted.",
          },
          {
            title: "Adaptive questions",
            body: "Questions can target comprehension, application, curiosity, visualization, metacognition or anticipation. The web path mainly uses the visible page, profile, live gauges and past difficulties.",
            user: "The question arrives in the context of the page being read.",
            system: "The guided question and answer are persisted in the pedagogical tables.",
          },
          {
            title: "Immediate feedback",
            body: "The answer is evaluated with a correct, partial or incorrect verdict, then feedback. The goal is not only to score, but to correct the strategy.",
            user: "The student sees what is correct and what needs work.",
            system: "Verdicts feed live gauges, history and recurring difficulties.",
          },
          {
            title: "Flashcards",
            body: "Cards extend active recall after reading. They can be reviewed outside a session or at the beginning of a new session on the same document.",
            user: "A front/back card turns a useful answer into material to review.",
            system: "Review date, document and difficulty guide the warm-up.",
          },
          {
            title: "Exit airlock",
            body: "The web summary records reflections and consolidates the profile from live gauges or, as fallback, from success metrics.",
            user: "The session ends with a few personal answers.",
            system: "Reflections are stored and the lasting profile is nudged at session end.",
          },
        ],
      },
      {
        id: "gauges",
        title: "What the gauges mean",
        intro: "These criteria are pedagogical landmarks, not diagnoses.",
        cards: [
          { title: "Attention", body: "Engagement in the task, reading stability and ability to complete an answer." },
          { title: "Context comprehension", body: "Ability to answer from the right passage rather than guessing off-topic." },
          { title: "Creativity", body: "Ability to produce a useful analogy, example or personal connection." },
          { title: "Retention", body: "Ability to actively recall information, especially in quizzes and flashcards." },
          { title: "Curiosity", body: "Ability to formulate questions or connections that extend the course without drifting." },
          { title: "Metacognition", body: "Ability to name one's blocks, choose a strategy and define a next action." },
        ],
      },
      {
        id: "science",
        title: "Scientific experiments and results used",
        cards: [
          {
            title: "Metacognitive monitoring and control",
            body: "Flavell then Dunlosky & Metcalfe describe metacognition as a monitoring/control pair: observing comprehension, then acting on strategy. Meta-Capp applies this with gauges, anticipation questions and reflection questions.",
          },
          {
            title: "Self-regulated learning",
            body: "Zimmerman presents self-regulated learning as a cycle: preparation, controlled action, then self-reflection. The entry and exit airlocks frame this cycle.",
          },
          {
            title: "Retrieval practice",
            body: "Roediger & Karpicke show that self-testing does not only measure memory: active recall improves long-term retention. This justifies guided questions and flashcards.",
          },
          {
            title: "Formative feedback",
            body: "Hattie & Timperley show that useful feedback says what has been achieved, what is missing and what to do next. Meta-Capp translates this into verdicts, supplements, hints and rephrasing.",
          },
          {
            title: "Self-explanation",
            body: "Chi and colleagues showed that asking students to explain in their own words can improve comprehension. Open answers and rephrasing use this principle.",
          },
          {
            title: "Curiosity and knowledge gap",
            body: "Loewenstein links curiosity to the gap between what one knows and wants to understand. Kang et al. show that epistemic curiosity activates reward circuitry and can improve later recall.",
          },
          {
            title: "Visualization and multiple representations",
            body: "Ainsworth shows that multiple representations can help learning when they support a clear cognitive task. Visualization questions are useful for figures, mechanisms and spatial relationships.",
          },
          {
            title: "Wakeful rest after learning",
            body: "Dewar et al., at the University of Edinburgh, compared 10 minutes of wakeful rest after verbal learning with a visual spot-the-difference task. Rest improved recall after 15-30 minutes and again after 7 days. The final rest airlock keeps a short, non-intrusive version.",
          },
        ],
      },
      {
        id: "memory",
        title: "Learning methods included in the page",
        intro:
          "These methods make metacognition actionable: the student does not only read, but checks, retrieves, spaces, mixes, explains and connects learning to personal questions.",
        cards: [
          {
            title: "Why passive re-reading is not enough",
            body: "Re-reading often gives a feeling of familiarity, but it does not prove that information can be recalled without support. Meta-Capp therefore asks students to produce answers.",
          },
          {
            title: "Active retrieval",
            body: "Bringing information back from memory is harder than re-reading, but this difficulty consolidates the trace and reveals gaps.",
          },
          {
            title: "Spaced repetition",
            body: "Ebbinghaus describes memory fragility over time; Cepeda et al. show the value of distributed practice. Flashcards turn forgetting into a review signal.",
          },
          {
            title: "Leitner system",
            body: "A successful card returns less often; a failed card returns sooner. The useful principle is simple: success, hesitation and forgetting guide the next review.",
          },
          {
            title: "Interleaving",
            body: "Mixing nearby types forces students to choose the right strategy instead of applying a reflex. Meta-Capp therefore varies question types.",
          },
          {
            title: "Desirable difficulties",
            body: "Bjork & Bjork describe difficulties that slow the feeling of ease but strengthen learning: active recall, spacing, variation and self-explanation.",
          },
          {
            title: "Curiosity priming",
            body: "An intriguing question creates a cognitive gap. The entry hook helps the learner start with active expectation rather than passive reading.",
          },
          {
            title: "Consolidation pause",
            body: "Post-learning wakeful rest reduces immediate interference. Meta-Capp adapts it as one minute without new stimulation after the summary.",
          },
          {
            title: "Feynman method and personal questions",
            body: "Explaining simply, identifying fuzzy areas, returning to the source and explaining again helps turn vague understanding into a usable model.",
          },
        ],
      },
    ],
    referencesTitle: "Scientific sources",
    referencesIntro: "References ported from the existing Tkinter page, with the explicit addition of Dewar et al. on wakeful rest.",
    references: referencesEn,
  },
};

export const whyContent: Record<Lang, Record<WhyKey, WhyContent>> = {
  fr: {
    entry: {
      title: "Pourquoi ce sas d'entrée ?",
      principle:
        "Zimmerman décrit l'apprentissage auto-régulé comme un cycle qui commence par une phase de préparation. Loewenstein et Kang et al. montrent aussi qu'un écart de curiosité peut augmenter l'engagement et faciliter le rappel.",
      conclusion:
        "Entrer directement dans un PDF pousse souvent à lire en pilote automatique. Une intention courte et une accroche intrigante aident à passer d'une navigation passive à une session d'apprentissage.",
      inApp:
        "Meta-Capp utilise donc un court ralentissement, un compte à rebours et une accroche générée par Gemma avant la lecture.",
      sources: ["Zimmerman (2002)", "Loewenstein (1994)", "Kang et al. (2009)"],
    },
    warmup: {
      title: "Pourquoi cette révision éclair ?",
      principle:
        "Roediger & Karpicke montrent que le rappel actif améliore la rétention à long terme. Ebbinghaus, Cepeda et Leitner justifient l'espacement et le retour plus rapide des cartes fragiles.",
      conclusion:
        "Se tester brièvement avant de continuer réactive ce qui est déjà fragile et évite d'empiler de nouvelles informations sur une trace instable.",
      inApp:
        "Meta-Capp propose les cartes dues du document avant la lecture, sans bloquer l'utilisateur si aucune carte n'est prête.",
      sources: ["Roediger & Karpicke (2006)", "Ebbinghaus (1885/1913)", "Cepeda et al. (2006)", "Leitner (1972/1973)"],
    },
    exit: {
      title: "Pourquoi ce bilan ?",
      principle:
        "Flavell et Dunlosky & Metcalfe décrivent la métacognition comme observer sa compréhension puis choisir une stratégie. Zimmerman place l'auto-réflexion à la fin du cycle d'apprentissage.",
      conclusion:
        "Nommer ce qui a bloqué, ce qui a aidé et ce qui reste fragile transforme une session terminée en information exploitable pour la prochaine.",
      inApp:
        "Meta-Capp enregistre ces réponses de réflexion et finalise la session ; le profil durable est ensuite consolidé depuis les jauges live ou les métriques disponibles.",
      sources: ["Flavell (1979)", "Dunlosky & Metcalfe (2009)", "Zimmerman (2002)", "Hattie & Timperley (2007)"],
    },
    postExitRest: {
      title: "Pourquoi une minute sans rien faire ?",
      principle:
        "Dewar et al., à l'Université d'Édimbourg, ont étudié le repos éveillé après un apprentissage verbal : 10 minutes de repos ont amélioré le rappel par rapport à une tâche visuelle.",
      conclusion:
        "Le bénéfice était visible après 15-30 minutes et encore après 7 jours, ce qui suggère que l'activité juste après l'apprentissage peut influencer la consolidation.",
      inApp:
        "Meta-Capp n'impose pas 10 minutes : il garde une version courte de 60 secondes, sans nouvelle stimulation, pour fermer la session proprement.",
      sources: ["Dewar et al. (2012)"],
    },
  },
  en: {
    entry: {
      title: "Why this entry airlock?",
      principle:
        "Zimmerman describes self-regulated learning as a cycle that starts with preparation. Loewenstein and Kang et al. also show that a curiosity gap can increase engagement and support later recall.",
      conclusion:
        "Jumping straight into a PDF often encourages autopilot reading. A short intention and an intriguing hook help move from passive browsing to a learning session.",
      inApp: "Meta-Capp therefore uses a short slowdown, countdown and Gemma-generated hook before reading.",
      sources: ["Zimmerman (2002)", "Loewenstein (1994)", "Kang et al. (2009)"],
    },
    warmup: {
      title: "Why this quick review?",
      principle:
        "Roediger & Karpicke show that active recall improves long-term retention. Ebbinghaus, Cepeda and Leitner justify spacing and bringing fragile cards back sooner.",
      conclusion:
        "Testing yourself briefly before continuing reactivates fragile knowledge and avoids stacking new information on an unstable trace.",
      inApp: "Meta-Capp offers due cards from the document before reading, without blocking the user when no card is ready.",
      sources: ["Roediger & Karpicke (2006)", "Ebbinghaus (1885/1913)", "Cepeda et al. (2006)", "Leitner (1972/1973)"],
    },
    exit: {
      title: "Why this summary?",
      principle:
        "Flavell and Dunlosky & Metcalfe describe metacognition as observing comprehension then choosing a strategy. Zimmerman places self-reflection at the end of the learning cycle.",
      conclusion:
        "Naming what blocked you, what helped and what remains fragile turns a finished session into useful information for the next one.",
      inApp:
        "Meta-Capp records these reflection answers and finalizes the session; the lasting profile is then consolidated from live gauges or available metrics.",
      sources: ["Flavell (1979)", "Dunlosky & Metcalfe (2009)", "Zimmerman (2002)", "Hattie & Timperley (2007)"],
    },
    postExitRest: {
      title: "Why one minute of doing nothing?",
      principle:
        "Dewar et al., at the University of Edinburgh, studied wakeful rest after verbal learning: 10 minutes of rest improved recall compared with a visual task.",
      conclusion:
        "The benefit appeared after 15-30 minutes and again after 7 days, suggesting that activity right after learning can influence consolidation.",
      inApp:
        "Meta-Capp does not impose 10 minutes: it keeps a short 60-second version, without new stimulation, to close the session cleanly.",
      sources: ["Dewar et al. (2012)"],
    },
  },
};
