"use client";

import { useState } from "react";
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
const fillBtn = { padding: "8px 14px", fontSize: 14, flex: "0 0 auto", background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" } as const;

// Материал-блок (отдельная карточка): ссылка на товар → автозаполнение параметров; лид (боты/почта);
// параметры материала сворачиваемым аккордеоном («ввести вручную» / авто после ввода ссылки).
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
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [expanded, setExpanded] = useState(false);
  const [modal, setModal] = useState(false);

  async function go() {
    if (!value) return;
    setState("loading");
    onUrl(value); // ссылка сохраняется в позицию сметы даже при неудаче парса
    setExpanded(true); // раскрываем параметры — проверить/поправить автозаполнение
    try {
      const res = await fetch("/api/calc/parse-link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: value, kind }),
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
      <span style={{ fontSize: 14, fontWeight: 500 }}>
        Добавьте ссылку на {CALC_META[kind].accYour}. Мы заполним параметры сами. Если оставите e-mail
        или подпишетесь на бот, поищем, где дешевле и сообщим.
      </span>

      <div className="row" style={{ gap: 6 }}>
        <input style={inp} placeholder="Вставьте ссылку из магазина" value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="button" className="btn" style={fillBtn} onClick={go} disabled={state === "loading"}>
          {state === "loading" ? "…" : "Заполнить"}
        </button>
      </div>
      {state === "done" && <span className="muted" style={{ fontSize: 13 }}>Заполнили из ссылки — проверьте и поправьте.</span>}
      {state === "error" && <span className="muted" style={{ fontSize: 13 }}>Не удалось прочитать страницу — впишите параметры вручную (ссылка сохранена).</span>}

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
