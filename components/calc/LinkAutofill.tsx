"use client";

import { useEffect, useRef, useState } from "react";
import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { CALC_META } from "@/lib/estimate/companions";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { LoadingIndicator } from "@/components/application/loading-indicator/loading-indicator";
import { MaterialParams } from "./MaterialParams";

// Материал-блок (отдельная карточка, рекламный вид): вставил ссылку → сервер сам читает страницу
// (прямой запрос → резидентский прокси для магазинов, режущих ДЦ-IP) → авто-подгрузка параметров.
// Параметры — свёрнуты, раскрываются по ссылке или «ввести вручную».
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
  const [slow, setSlow] = useState(false); // >2.5 с — идём через прокси, дольше: успокаиваем «подождите»
  const [expanded, setExpanded] = useState(false);
  const [parsedTitle, setParsedTitle] = useState<string | null>(null);
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
    setSlow(false);
    setExpanded(true); // сразу раскрываем — крутилка, ниже подгрузятся поля
    onUrl(v); // ссылка сохраняется в позицию сметы даже при неудаче парса
    const slowTimer = setTimeout(() => setSlow(true), 2500); // магазин отвечает через прокси — дольше
    try {
      const res = await fetch("/api/calc/parse-link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: v, kind }),
      });
      const data = await res.json();
      if (data?.ok && data.spec && Object.keys(data.spec).length > 0) {
        (onAutoSpec ?? onSpec)(data.spec);
        setParsedTitle(typeof data.title === "string" && data.title.trim() ? data.title.trim() : null);
        setState("done");
      } else {
        setState("error");
      }
    } catch {
      setState("error");
    } finally {
      clearTimeout(slowTimer);
    }
  }

  return (
    <div className="card stack">
      {/* Шаг 1 — ссылка: выгода вперёд, чтобы охотнее вставляли (→ реф-ссылка). */}
      <div className="stack" style={{ gap: 4 }}>
        <strong style={{ fontSize: 17 }}>Вставьте ссылку на {CALC_META[kind].acc}, заполним параметры за вас</strong>
        <span className="muted" style={{ fontSize: 14 }}>Не придётся вводить размеры и цену вручную.</span>
      </div>

      <Input size="sm" placeholder="Ссылка на товар из магазина" value={value} onChange={setValue} />
      {state === "loading" && (
        <span className="muted" style={{ fontSize: 14, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <LoadingIndicator type="line-simple" size="sm" />
          {slow ? "Читаем страницу магазина — это займёт несколько секунд, подождите…" : "Читаем страницу…"}
        </span>
      )}
      {state === "done" && (
        <span className="muted" style={{ fontSize: 14 }}>
          Готово: параметры заполнены, проверьте ниже.
          {parsedTitle && <><br />Нашли: <strong style={{ fontWeight: 600 }}>{parsedTitle.slice(0, 90)}</strong></>}
        </span>
      )}
      {state === "error" && (
        <span className="text-sm font-semibold text-error-primary">
          Не удалось прочитать страницу — заполните параметры ниже вручную (ссылка сохранена).
        </span>
      )}

      <Button type="button" color="link-gray" size="sm" className="self-start underline" onClick={() => setExpanded((v) => !v)}>
        {expanded ? "скрыть параметры" : "ввести параметры вручную"}
      </Button>
      {expanded && <MaterialParams kind={kind} spec={spec} onChange={onSpec} autoKeys={autoKeys} />}
    </div>
  );
}
