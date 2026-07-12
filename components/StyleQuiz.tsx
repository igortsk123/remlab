"use client";

import { useState } from "react";
import Link from "next/link";
import { QUIZ_CARDS, STYLES, tallyStyle, type StyleId } from "@/lib/styles/quiz";
import { trackQuizCompleted } from "@/app/styles-actions";

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
      if (top) void trackQuizCompleted(top);
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
            Ничего страшного — вкус штука тонкая. Полистайте примеры ещё раз или сразу переходите к расчёту.
          </p>
          <div className="row">
            <button className="btn btn-secondary" onClick={restart}>Пройти заново</button>
            <Link className="btn" href="/calc">Посчитать материалы</Link>
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
          <Link className="btn" href="/start">Показать мою комнату в этом стиле</Link>
          <Link className="btn btn-secondary" href="/calc">Собрать смету</Link>
        </div>
        <button className="quiz-link" onClick={restart}>Пройти заново</button>
      </div>
    );
  }

  const card = QUIZ_CARDS[index];
  if (!card) return null;
  const info = STYLES[card.style];
  return (
    <div className="card stack quiz">
      <div className="progress" aria-hidden>
        {QUIZ_CARDS.map((c, i) => (
          <span key={c.id} data-on={i <= index} />
        ))}
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>Карточка {index + 1} из {TOTAL}</p>
      <div
        className="quiz-swatch"
        style={{ background: `linear-gradient(135deg, ${info.swatch[0]}, ${info.swatch[1]})` }}
        aria-hidden
      />
      <p style={{ margin: 0, minHeight: 44 }}>{card.caption}</p>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <button className="btn btn-secondary btn-block" onClick={() => answer(false)}>Не моё</button>
        <button className="btn btn-block" onClick={() => answer(true)}>Нравится</button>
      </div>
    </div>
  );
}
