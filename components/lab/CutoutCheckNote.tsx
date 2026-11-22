"use client";

// «Что не так?» — необязательный текст карточки вырезки, сохраняется сам (та же сохранялка, что у /lab/mesh-check): через 1 с после ввода,
// при уходе из поля, при закрытии вкладки. Черновик живёт в браузере до ответа сервера. Ключ черновика с приставкой — не пересекается с mesh-check.

import { useEffect, useRef, useState } from "react";
import { beaconNote, editorId, nonce, sendNote } from "@/lib/cutout-check/client";
import { L } from "@/lib/cutout-check/rules";
import type { CutoutItemView } from "@/lib/cutout-check/types";
import { createNoteSaver, draftKey, NOTE_MAX, restoreDraft, type NoteSaver, type SaveState } from "@/lib/mesh-audit/note-saver";

const P = "cutout:";
const store = {
  get: (k: string) => {
    try {
      return localStorage.getItem(P + k);
    } catch {
      return null;
    }
  },
  set: (k: string, v: string) => {
    try {
      localStorage.setItem(P + k, v);
    } catch {
      // приватный режим: остаётся сервер и маяк
    }
  },
  del: (k: string) => {
    try {
      localStorage.removeItem(P + k);
    } catch {
      // нет хранилища — нечего чистить
    }
  },
};

const LABEL: Record<SaveState, string> = { idle: "", saving: "сохраняю… / saving…", saved: "сохранено ✓ / saved ✓", error: "не сохранилось, повторю / not saved, retrying" };

export function CutoutCheckNote({ item, reviewer, saverRef }: { item: CutoutItemView; reviewer: string; saverRef?: { current: NoteSaver | null } }) {
  const [text, setText] = useState(item.note ?? "");
  const [state, setState] = useState<SaveState>("idle");
  const saver = useRef<NoteSaver | null>(null);
  const area = useRef<HTMLTextAreaElement | null>(null);
  const serverSeq = useRef(item.noteSeq);

  useEffect(() => {
    const draft = restoreDraft(store, { itemId: item.id, generationKey: item.generationKey }, serverSeq.current);
    const s = createNoteSaver(
      { itemId: item.id, generationKey: item.generationKey, reviewer, editorId: editorId() },
      {
        send: sendNote,
        beacon: beaconNote,
        store,
        now: () => Date.now(),
        newId: nonce,
        setTimer: (fn, ms) => window.setTimeout(fn, ms), // обёртки обязательны: setTimeout как метод объекта падает «Illegal invocation»
        clearTimer: (t) => window.clearTimeout(t as number),
        onState: setState,
      },
      draft,
    );
    saver.current = s;
    if (saverRef) saverRef.current = s;
    if (draft) {
      setText(draft.body);
      void s.flush();
    } else {
      store.del(draftKey(item.id, item.generationKey));
    }
    const onHide = () => s.closing();
    const onVis = () => document.visibilityState === "hidden" && s.closing();
    window.addEventListener("pagehide", onHide);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onVis);
      s.closing();
      if (saverRef?.current === s) saverRef.current = null;
    };
  }, [item.id, item.generationKey, reviewer, saverRef]);

  useEffect(() => {
    const el = area.current; // поле растёт по тексту
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [text]);

  const label = `${L.note.ru} / ${L.note.en}`;
  return (
    <div className="relative">
      <textarea
        ref={area}
        rows={1}
        maxLength={NOTE_MAX}
        value={text}
        placeholder={label}
        aria-label={label}
        onChange={(e) => {
          setText(e.target.value);
          saver.current?.input(e.target.value);
        }}
        onBlur={() => void saver.current?.flush()}
        className="block min-h-11 w-full resize-none overflow-hidden rounded-lg bg-primary px-3 pt-2.5 pb-5 text-sm text-primary shadow-xs ring-1 ring-primary outline-hidden ring-inset placeholder:text-tertiary focus:ring-2 focus:ring-brand"
      />
      {state !== "idle" && (
        <span className={`pointer-events-none absolute right-2 bottom-1 text-xs ${state === "saved" ? "text-success-primary" : state === "error" ? "text-error-primary" : "text-tertiary"}`}>
          {LABEL[state]}
        </span>
      )}
    </div>
  );
}
