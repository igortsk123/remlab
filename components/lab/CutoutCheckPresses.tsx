"use client";

// Кнопки «Ок» / «Не ок» карточки вырезки: нажатая — сплошной цвет, повтор того же снимает отметку. Подписи парой RU/EN. Тап-зона ≥ 44 px.

import { L, type Mark } from "@/lib/cutout-check/rules";

interface Props {
  mark: string | null;
  busy: boolean;
  onPress: (p: Mark) => void;
}

const BASE = "flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-lg px-2 text-sm font-semibold ring-1 ring-inset transition disabled:opacity-60";
const IDLE = "bg-primary text-secondary ring-primary";

function Label({ ru, en }: { ru: string; en: string }) {
  return (
    <span className="flex flex-col items-center leading-tight">
      <span>{ru}</span>
      <span className="text-[11px] font-normal opacity-80">{en}</span>
    </span>
  );
}

export function CutoutCheckPresses({ mark, busy, onPress }: Props) {
  return (
    <div className="flex gap-2" role="group" aria-label="Оценка вырезки / Cutout verdict">
      <button
        type="button"
        aria-pressed={mark === "ok"}
        disabled={busy}
        onClick={() => onPress("ok")}
        className={`${BASE} ${mark === "ok" ? "bg-success-solid text-white ring-transparent" : IDLE}`}
      >
        ✓ <Label {...L.ok} />
      </button>
      <button
        type="button"
        aria-pressed={mark === "bad"}
        disabled={busy}
        onClick={() => onPress("bad")}
        className={`${BASE} ${mark === "bad" ? "bg-error-solid text-white ring-transparent" : IDLE}`}
      >
        ✕ <Label {...L.bad} />
      </button>
    </div>
  );
}
