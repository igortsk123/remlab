"use client";

import { useState } from "react";
import { QUIZ_CARDS, STYLES, tallyStyle, type StyleId } from "@/lib/styles/quiz";
import { completeQuiz } from "@/app/styles-actions";
import { Button } from "@/components/base/buttons/button";
import { ProgressBarBase } from "@/components/base/progress-indicators/progress-indicators";

// Игра-карточки «Узнай свой вкус»: листаем интерьеры «Нравится / Не моё» → в конце показываем стиль.
// Картинки пока плейсхолдеры (палитра-градиент из swatch). Состояния экрана: игра / результат /
// результат-без-лайков (нейтральный). Асинхронности нет — loading/error не требуются.

const TOTAL = QUIZ_CARDS.length;

export function StyleQuiz() {
  const [index, setIndex] = useState(0);
  const [liked, setLiked] = useState<StyleId[]>([]);
  const [done, setDone] = useState(false);

  function answer(like: boolean) {
    const card = QUIZ_CARDS[index];
    if (!card) return;
    const nextLiked = like ? [...liked, card.style] : liked;
    if (like) setLiked(nextLiked);
    if (index + 1 >= TOTAL) {
      setDone(true);
      const top = tallyStyle(nextLiked);
      if (top) void completeQuiz(top);
    } else {
      setIndex(index + 1);
    }
  }

  function restart() {
    setIndex(0);
    setLiked([]);
    setDone(false);
  }

  if (done) {
    const top = tallyStyle(liked);
    if (!top) {
      return (
        <div className="card stack quiz-result">
          <p className="eyebrow">Готово</p>
          <h2 style={{ margin: 0 }}>Пока ничего не приглянулось</h2>
          <p className="muted" style={{ margin: 0 }}>
            Ничего страшного, вкус штука тонкая. Полистайте примеры ещё раз или сразу переходите к расчёту.
          </p>
          <div className="row">
            <Button color="secondary" size="lg" onClick={restart}>Пройти заново</Button>
            <Button size="lg" href="/calc">Посчитать материалы</Button>
          </div>
        </div>
      );
    }
    const info = STYLES[top];
    return (
      <div className="card stack quiz-result">
        <p className="eyebrow">Ваш стиль</p>
        <div
          className="quiz-swatch quiz-swatch--result"
          style={{ background: `linear-gradient(135deg, ${info.swatch[0]}, ${info.swatch[1]})` }}
          aria-hidden
        />
        <h2 style={{ margin: 0 }}>{info.name}</h2>
        <p className="muted" style={{ margin: 0 }}>{info.blurb}</p>
        <div className="row">
          <Button size="lg" href="/start">Показать мою комнату в этом стиле</Button>
          <Button color="secondary" size="lg" href="/calc">Посчитать материалы</Button>
        </div>
        <Button color="link-gray" size="sm" className="self-start underline" onClick={restart}>Пройти заново</Button>
      </div>
    );
  }

  const card = QUIZ_CARDS[index];
  if (!card) return null;
  const info = STYLES[card.style];
  return (
    <div className="card stack quiz">
      <div aria-hidden className="mb-1">
        <ProgressBarBase value={index + 1} min={0} max={TOTAL} />
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>Карточка {index + 1} из {TOTAL}</p>
      <div
        className="quiz-swatch"
        style={{ background: `linear-gradient(135deg, ${info.swatch[0]}, ${info.swatch[1]})` }}
        aria-hidden
      />
      <p style={{ margin: 0, minHeight: 44 }}>{card.caption}</p>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <Button color="secondary" size="lg" className="w-full" onClick={() => answer(false)}>Не моё</Button>
        <Button size="lg" className="w-full" onClick={() => answer(true)}>Нравится</Button>
      </div>
    </div>
  );
}
