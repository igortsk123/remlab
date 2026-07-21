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
// (крутилка → поля); лид (боты/почта). Параметры — свёрнуты, раскрываются по ссылке или «ввести вручную».
export function LinkAutofill({
  kind,
  url,
  onUrl,
  spec,
  onSpec,
}: {
  kind: CalcKind;
  url: string | undefined;
  onUrl: (url: string) => void;
  spec: MaterialSpec;
  onSpec: (patch: Partial<MaterialSpec>) => void;
}) {
  const [value, setValue] = useState(url ?? "");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [expanded, setExpanded] = useState(false);
  const lastParsed = useRef<string>(url ?? ""); // чтобы сохранённая ссылка не перепарсивалась при монтировании

  // Автоподгрузка: как только введена/вставлена ссылка (с небольшой задержкой) — читаем страницу.
  useEffect(() => {
    const v = value.trim();
    if (!/^https?:\/\//i.test(v) || v === lastParsed.current) return;
    const t = setTimeout(() => { void parse(v); }, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

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
      if (data?.ok && data.spec && Object.keys(data.spec).length > 0) {
        onSpec(data.spec);
        setState("done");
      } else {
        setState("error");
      }
    } catch {
      setState("error");
    }
  }

  return (
    <div className="card stack">
      {/* Шаг 1 — ссылка: выгода вперёд, чтобы охотнее вставляли (→ реф-ссылка). */}
      <div className="stack" style={{ gap: 4 }}>
        <strong style={{ fontSize: 17 }}>Вставьте ссылку — заполним параметры за вас</strong>
        <span className="muted" style={{ fontSize: 13 }}>
          Ссылку на {CALC_META[kind].accYour} — не придётся вводить размеры и цену вручную.
        </span>
      </div>

      <input style={inp} placeholder="Ссылка на товар из магазина" value={value} onChange={(e) => setValue(e.target.value)} />
      {state === "loading" && (
        <span className="muted" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span className="spinner" aria-hidden="true" /> Читаем страницу…
        </span>
      )}
      {state === "done" && <span className="muted" style={{ fontSize: 13 }}>Готово — параметры заполнены, проверьте ниже.</span>}
      {state === "error" && <span className="muted" style={{ fontSize: 13 }}>Не удалось прочитать страницу — заполните параметры ниже (ссылка сохранена).</span>}

      <button type="button" className="quiz-link" style={{ fontSize: 13 }} onClick={() => setExpanded((v) => !v)}>
        {expanded ? "скрыть параметры" : "ввести параметры вручную"}
      </button>
      {expanded && <MaterialParams kind={kind} spec={spec} onChange={onSpec} />}
    </div>
  );
}
