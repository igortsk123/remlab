"use client";

// «Кто проверяет» — один раз при входе (T-20261112-118, ответ владельца 4): имя хранится в браузере и уходит в журнал каждого
// нажатия и каждой версии комментария (`mesh_audit_marks.reviewer`, `mesh_audit_notes.reviewer`). Сменить — ссылка в шапке.

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";

const KEY = "mesh-check-reviewer";
const ReviewerCtx = createContext<string>("");

export function useReviewer(): string {
  return useContext(ReviewerCtx);
}

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function MeshCheckReviewer({ children }: { children: ReactNode }) {
  const [name, setName] = useState<string | null>(null); // null — ещё не прочитали браузер
  const [draft, setDraft] = useState("");
  useEffect(() => setName(read()), []);

  function save() {
    const v = draft.trim().slice(0, 40);
    if (!v) return;
    try {
      localStorage.setItem(KEY, v);
    } catch {
      // приватный режим: имя живёт до закрытия вкладки
    }
    setName(v);
  }

  if (name === null) return null;
  if (!name) {
    return (
      // отступ 16 px по краям, как у основной страницы (снимок 375-who: поле прижималось к краям); ширина не больше 384 px
      <div className="mx-auto flex w-full max-w-sm flex-col gap-3 px-4 py-10">
        <h1 className="text-lg font-semibold text-primary">Кто проверяет?</h1>
        <Input aria-label="Имя" value={draft} onChange={setDraft} placeholder="Имя" />
        <Button color="primary" onClick={save} isDisabled={!draft.trim()}>
          Начать
        </Button>
      </div>
    );
  }
  return (
    <ReviewerCtx.Provider value={name}>
      {children}
      <p className="pt-4 text-center text-xs text-tertiary">
        проверяет {name} ·{" "}
        <button type="button" className="underline" onClick={() => setName("")}>
          сменить
        </button>
      </p>
    </ReviewerCtx.Provider>
  );
}
