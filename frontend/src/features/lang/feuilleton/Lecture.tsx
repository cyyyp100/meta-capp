// Lecture — L'étape « lecture » : UNE lecture de l'épisode, aide à la demande.
//
// Elle remplace les deux passages et les notes : le texte s'affiche sans
// traduction ; un mot se touche (sa bulle, comptée comme une révélation), une
// réplique se traduit sur demande, et aux premiers paliers « Tout traduire »
// est proposé (le serveur dit lequel : `translate_all`). Chaque traduction
// montrée part en un événement `line` : une réplique traduite ne compte ni
// comme reconnue ni comme ratée. Les notes s'ouvrent sous leur réplique.
// La lecture se ferme sur « compris / à peu près / pas compris ».
import { useState } from "react";

import type { EpisodeNote } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { EpisodeText } from "./EpisodeText";
import { episodeOf, revealFor, type StepProps, Understood } from "./Steps";
import { Card, chipBtn, StepTitle } from "./ui";

export function LectureStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref)!;
  const [allPinyin, setAllPinyin] = useState(false);
  const notes = (step.notes as EpisodeNote[]) ?? [];
  return (
    <Card>
      <StepTitle hint={step.translate_all ? t("feuil.lecture.hint_all") : t("feuil.lecture.hint")}>
        {`${t("feuil.episode_n", { n: episode.n })} — ${episode.title}`}
      </StepTitle>
      {episode.kind === "respiration" && (
        <p style={{ color: "var(--muted)", marginTop: -6 }}>{t("feuil.respiration")}</p>
      )}
      {notes.length > 0 && <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -6 }}>{t("feuil.lecture.notes_hint")}</p>}
      {episode.family === "hanzi" && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <button style={chipBtn(allPinyin)} onClick={() => setAllPinyin((v) => !v)}>{t("feuil.all_pinyin")}</button>
        </div>
      )}
      <EpisodeText
        episode={episode}
        translation={step.translate_all ? "toggle" : "lines"}
        onReveal={revealFor(tracker, episode, "lecture")}
        onLineShown={(line, all) => tracker.push({ type: "line", episode_id: episode.id, line, pass: "lecture", all })}
        notes={notes}
        showPinyinAll={allPinyin}
      />
      <Understood onPick={(signal) => onNext({ signal })} />
    </Card>
  );
}
