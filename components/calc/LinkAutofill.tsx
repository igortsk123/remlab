"use client";

import { useEffect, useRef, useState } from "react";
import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { CALC_META } from "@/lib/estimate/companions";
import { MaterialParams } from "./MaterialParams";
import { LeadModal } from "./LeadModal";

const TG_BOT = process.env.NEXT_PUBLIC_TELEGRAM_BOT;
const MAX_BOT = process.env.NEXT_PUBLIC_MAX_BOT;

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
  const [modal, setModal] = useState(false);
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

  const tgHref = TG_BOT ? `https://t.me/${TG_BOT}` : null;
  const maxHref = MAX_BOT ? `https://max.ru/${MAX_BOT}` : null;

  return (
    <div className="card stack">
      <strong style={{ fontSize: 17 }}>Добавьте ссылку на {CALC_META[kind].accYour}</strong>
      <ul className="checklist">
        <li>Заполним параметры расчёта сами</li>
        <li>Найдём, где дешевле, и пришлём вам</li>
        <li>Подскажем, что ещё нужно купить</li>
      </ul>
      <span className="muted" style={{ fontSize: 13 }}>
        Оставьте e-mail или подпишитесь на бот — сообщим, когда найдём выгоднее.
      </span>

      <input style={inp} placeholder="Вставьте ссылку из магазина" value={value} onChange={(e) => setValue(e.target.value)} />
      {state === "loading" && (
        <span className="muted" style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span className="spinner" aria-hidden="true" /> Читаем страницу…
        </span>
      )}
      {state === "done" && <span className="muted" style={{ fontSize: 13 }}>Заполнили из ссылки — проверьте и поправьте ниже.</span>}
      {state === "error" && <span className="muted" style={{ fontSize: 13 }}>Не смогли прочитать страницу — впишите параметры вручную (ссылка сохранена).</span>}

      <div className="row" style={{ gap: 8 }}>
        {tgHref
          ? <a className="chip" href={tgHref} target="_blank" rel="noopener noreferrer">Телеграм</a>
          : <button type="button" className="chip">Телеграм</button>}
        {maxHref
          ? <a className="chip" href={maxHref} target="_blank" rel="noopener noreferrer">MAX</a>
          : <button type="button" className="chip">MAX</button>}
        <button type="button" className="chip" onClick={() => setModal(true)}>✉ Сообщить по почте</button>
      </div>

      <button type="button" className="quiz-link" style={{ fontSize: 13 }} onClick={() => setExpanded((v) => !v)}>
        {expanded ? "скрыть параметры" : "ввести вручную"}
      </button>
      {expanded && <MaterialParams kind={kind} spec={spec} onChange={onSpec} />}

      {modal && <LeadModal kind={kind} url={value || url} onClose={() => setModal(false)} />}
    </div>
  );
}
