"use client";

import { useEffect, useRef, useState } from "react";
import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { CALC_META } from "@/lib/estimate/companions";
import { MaterialParams } from "./MaterialParams";

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Материал-блок (отдельная карточка, рекламный вид): вставил ссылку → авто-подгрузка параметров
// (крутилка → поля); магазин не отдаёт страницу (антибот) → загрузка сохранённой из браузера
// страницы (Ctrl+S). Параметры — свёрнуты, раскрываются по ссылке или «ввести вручную».
export function LinkAutofill({
  kind,
  url,
  onUrl,
  spec,
  onSpec,
  onAutoSpec,
  autoKeys,
}: {
  kind: CalcKind;
  url: string | undefined;
  onUrl: (url: string) => void;
  spec: MaterialSpec;
  onSpec: (patch: Partial<MaterialSpec>) => void; // ручной путь (MaterialParams) — снимает пометку «авто»
  onAutoSpec?: (spec: Partial<MaterialSpec>) => void; // авто из ссылки — стирает только прежние авто-поля
  autoKeys?: string[];
}) {
  const [value, setValue] = useState(url ?? "");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [parsedTitle, setParsedTitle] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const lastParsed = useRef<string>(url ?? ""); // чтобы сохранённая ссылка не перепарсивалась при монтировании

  // Автоподгрузка: как только введена/вставлена ссылка (с небольшой задержкой) — читаем страницу.
  useEffect(() => {
    const v = value.trim();
    if (!/^https?:\/\//i.test(v) || v === lastParsed.current) return;
    const t = setTimeout(() => { void parse(v); }, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Общий приём результата обоих путей (ссылка / загруженный файл сохранённой страницы).
  function applyResult(data: { ok?: boolean; title?: unknown; spec?: Partial<MaterialSpec> } | null, failCode: string) {
    if (data?.ok && data.spec && Object.keys(data.spec).length > 0) {
      (onAutoSpec ?? onSpec)(data.spec);
      setParsedTitle(typeof data.title === "string" && data.title.trim() ? data.title.trim() : null);
      setState("done");
    } else {
      setErrorCode(failCode);
      setState("error");
    }
  }

  async function parse(v: string) {
    lastParsed.current = v;
    setState("loading");
    setExpanded(true); // сразу раскрываем — крутилка, ниже подгрузятся поля
    onUrl(v); // ссылка сохраняется в позицию сметы даже при неудаче парса
    try {
      const res = await fetch("/api/calc/parse-link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: v, kind }),
      });
      const data = await res.json();
      applyResult(data, typeof data?.error === "string" ? data.error : "unreachable");
    } catch {
      setErrorCode("unreachable");
      setState("error");
    }
  }

  async function parseFile(file: File) {
    setState("loading");
    setExpanded(true);
    try {
      const html = (await file.text()).slice(0, 4_000_000);
      const res = await fetch("/api/calc/parse-html", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ html, kind }),
      });
      applyResult(await res.json(), "file_failed");
    } catch {
      setErrorCode("file_failed");
      setState("error");
    }
  }

  return (
    <div className="card stack">
      {/* Шаг 1 — ссылка: выгода вперёд, чтобы охотнее вставляли (→ реф-ссылка). */}
      <div className="stack" style={{ gap: 4 }}>
        <strong style={{ fontSize: 17 }}>Вставьте ссылку на {CALC_META[kind].acc}, заполним параметры за вас</strong>
        <span className="muted" style={{ fontSize: 14 }}>Не придётся вводить размеры и цену вручную.</span>
      </div>

      <input style={inp} placeholder="Ссылка на товар из магазина" value={value} onChange={(e) => setValue(e.target.value)} />
      {state === "loading" && (
        <span className="muted" style={{ fontSize: 14, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span className="spinner" aria-hidden="true" /> Читаем страницу…
        </span>
      )}
      {state === "done" && (
        <span className="muted" style={{ fontSize: 14 }}>
          Готово: параметры заполнены, проверьте ниже.
          {parsedTitle && <><br />Нашли: <strong style={{ fontWeight: 600 }}>{parsedTitle.slice(0, 90)}</strong></>}
        </span>
      )}
      {state === "error" && (
        <div className="stack" style={{ gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--danger)" }}>
            {errorCode === "needs_file"
              ? "Этот магазин не показывает страницу роботам."
              : errorCode === "file_failed"
                ? "Не получилось прочитать файл — введите параметры вручную."
                : "Не удалось прочитать страницу (ссылка сохранена)."}
          </span>
          {errorCode !== "file_failed" && (
            <span className="muted" style={{ fontSize: 14 }}>
              Можно так: откройте товар в браузере, сохраните страницу (Ctrl+S → «Веб-страница,
              только HTML») и загрузите файл сюда — заполним из него. Или введите параметры вручную.
            </span>
          )}
          <button type="button" className="quiz-link" style={{ fontSize: 14, alignSelf: "flex-start" }} onClick={() => fileRef.current?.click()}>
            Загрузить сохранённую страницу (.html)
          </button>
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept=".html,.htm,text/html"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = ""; // тот же файл можно выбрать повторно
          if (f) void parseFile(f);
        }}
      />

      <button type="button" className="quiz-link" style={{ fontSize: 14 }} onClick={() => setExpanded((v) => !v)}>
        {expanded ? "скрыть параметры" : "ввести параметры вручную"}
      </button>
      {expanded && <MaterialParams kind={kind} spec={spec} onChange={onSpec} autoKeys={autoKeys} />}
    </div>
  );
}
