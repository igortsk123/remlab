"use client";

// Комментарий карточки: необязательный, сохраняется сам (lib/mesh-audit/note-saver.ts) — через 1 с после ввода, при уходе из поля,
// при закрытии вкладки (sendBeacon). Черновик живёт в браузере до ответа сервера; после перезагрузки досылается.

import { useEffect, useRef, useState } from "react";
import { beaconNote, editorId, nonce, sendNote } from "@/lib/mesh-audit/check-client";
import { createNoteSaver, draftKey, NOTE_MAX, restoreDraft, type NoteSaver, type SaveState } from "@/lib/mesh-audit/note-saver";
import type { AuditItemView } from "@/lib/mesh-audit/types";

const store = {
  get: (k: string) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k: string, v: string) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      // приватный режим: остаётся сервер и маяк
    }
  },
  del: (k: string) => {
    try {
      localStorage.removeItem(k);
    } catch {
      // нет хранилища — нечего чистить
    }
  },
};

const LABEL: Record<SaveState, string> = { idle: "", saving: "сохраняю…", saved: "сохранено ✓", error: "не сохранилось, повторю" };

// saverRef отдаёт сохранялку карточке: перед «браком» текст досылается, чтобы решение ушло с последней версией.
export function MeshCheckNote({ item, reviewer, saverRef }: { item: AuditItemView; reviewer: string; saverRef?: { current: NoteSaver | null } }) {
  const [text, setText] = useState(item.note ?? "");
  const [state, setState] = useState<SaveState>("idle");
  const saver = useRef<NoteSaver | null>(null);
  const area = useRef<HTMLTextAreaElement | null>(null);
  const serverSeq = useRef(item.noteSeq); // версия сервера на момент показа: нажатия «ок»/«брак» её не меняют

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
        // обёртки обязательны: setTimeout, вызванный как метод объекта, в браузере падает «Illegal invocation» (снимок 00:26)
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (t) => window.clearTimeout(t as number),
        onState: setState,
      },
      draft, // черновик, которого сервер не видел, досылается той же версией (тот же opId — без второй строки)
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
    // телефон: свернули браузер — pagehide может не прийти вовсе, а вкладку потом убьёт система
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
    const el = area.current; // поле растёт по тексту — без ручки размера, она наезжала на «сохранено»
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [text]);

  return (
    <div className="relative">
      <textarea
        ref={area}
        rows={1}
        maxLength={NOTE_MAX}
        value={text}
        placeholder="Комментарий, необязательно"
        aria-label="Комментарий к модели, необязательно"
        onChange={(e) => {
          setText(e.target.value);
          saver.current?.input(e.target.value);
        }}
        onBlur={() => void saver.current?.flush()}
        className="block min-h-11 w-full resize-none overflow-hidden rounded-lg bg-primary px-3 pt-2.5 pb-5 text-sm text-primary shadow-xs ring-1 ring-primary outline-hidden ring-inset placeholder:text-placeholder focus:ring-2 focus:ring-brand"
      />
      {state !== "idle" && (
        <span className={`pointer-events-none absolute right-2 bottom-1 text-xs ${state === "saved" ? "text-success-primary" : state === "error" ? "text-error-primary" : "text-tertiary"}`}>
          {LABEL[state]}
        </span>
      )}
    </div>
  );
}
