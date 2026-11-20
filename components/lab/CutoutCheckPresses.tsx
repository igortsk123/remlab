"use client";

// Одна кнопка «Не ок» (владелец, TG 2098: «нажму, где не ок»): всё, что не нажато, считается «ок». Нажатая — сплошная красная, повтор снимает;
// у отмеченной ещё и мелкая ссылка «вернуть в ок». Подписи парой RU/EN. Тап-зона ≥ 44 px.

import { L, type Mark } from "@/lib/cutout-check/rules";

interface Props {
  mark: string | null;
  busy: boolean;
  onPress: (p: Mark) => void;
}

export function CutoutCheckPresses({ mark, busy, onPress }: Props) {
  const on = mark === "bad";
  const text = on ? L.badOn : L.bad;
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label="Оценка вырезки / Cutout verdict">
      <button
        type="button"
        aria-pressed={on}
        disabled={busy}
        onClick={() => onPress("bad")}
        className={`flex min-h-11 w-full items-center justify-center gap-2 rounded-lg px-3 text-sm font-semibold ring-1 ring-inset transition disabled:opacity-60 ${
          on ? "bg-error-solid text-white ring-transparent" : "bg-primary text-secondary ring-primary"
        }`}
      >
        <span aria-hidden="true">✕</span>
        <span className="flex flex-col items-center leading-tight">
          <span>{text.ru}</span>
          <span className="text-[11px] font-normal opacity-80">{text.en}</span>
        </span>
      </button>
      {on && (
        <button type="button" disabled={busy} onClick={() => onPress("ok")} className="min-h-8 self-start px-1 text-xs text-tertiary underline disabled:opacity-60">
          {L.undo.ru} / {L.undo.en}
        </button>
      )}
    </div>
  );
}
