"use client";

// Кнопки «ок» / «брак» карточки и окна увеличения: нажатая — сплошной цвет (успех/ошибка), повтор того же снимает отметку.
// Тап-зона ≥ 44 px (ui-rules).

import type { Press } from "@/lib/mesh-audit/check-client";

interface Props {
  mark: string | null;
  busy: boolean;
  onPress: (p: Press) => void;
  dark?: boolean; // в окне увеличения на тёмном фоне
}

const BASE = "flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-lg text-sm font-semibold ring-1 ring-inset transition disabled:opacity-60";

export function MeshCheckPresses({ mark, busy, onPress, dark }: Props) {
  const idle = dark ? "bg-transparent text-white ring-secondary_alt" : "bg-primary text-secondary ring-primary";
  return (
    <div className="flex gap-2" role="group" aria-label="Оценка модели">
      <button
        type="button"
        aria-pressed={mark === "ok"}
        disabled={busy}
        onClick={() => onPress("ok")}
        className={`${BASE} ${mark === "ok" ? "bg-success-solid text-white ring-transparent" : idle}`}
      >
        ✓ Ок
      </button>
      <button
        type="button"
        aria-pressed={mark === "bad"}
        disabled={busy}
        onClick={() => onPress("bad")}
        className={`${BASE} ${mark === "bad" ? "bg-error-solid text-white ring-transparent" : idle}`}
      >
        ✕ Брак
      </button>
    </div>
  );
}
