"use client";

import { useState } from "react";
import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { CALC_META } from "@/lib/estimate/companions";

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Вставить ссылку на товар → сервер тянет характеристики → заполняем параметры. Неудача → ручной ввод.
export function LinkAutofill({
  kind,
  url,
  onSpec,
  onUrl,
}: {
  kind: CalcKind;
  url: string | undefined;
  onSpec: (patch: Partial<MaterialSpec>) => void;
  onUrl: (url: string) => void;
}) {
  const [value, setValue] = useState(url ?? "");
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");

  async function go() {
    if (!value) return;
    setState("loading");
    onUrl(value); // ссылка сохраняется в позицию сметы даже при неудаче парса
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

  return (
    <div className="stack" style={{ gap: 6 }}>
      <span style={{ fontSize: 14, fontWeight: 500 }}>
        Добавьте ссылку на {CALC_META[kind].accYour}. Мы заполним параметры сами.
      </span>
      <div className="row" style={{ gap: 6 }}>
        <input style={inp} placeholder="Вставьте ссылку из магазина" value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="button" className="btn" style={{ padding: "8px 14px", fontSize: 14, flex: "0 0 auto", background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" }} onClick={go} disabled={state === "loading"}>
          {state === "loading" ? "…" : "Заполнить"}
        </button>
      </div>
      {state === "done" && <span className="muted" style={{ fontSize: 13 }}>Заполнили из ссылки — проверьте и поправьте.</span>}
      {state === "error" && <span className="muted" style={{ fontSize: 13 }}>Не удалось прочитать страницу — впишите параметры вручную (ссылка сохранена).</span>}
    </div>
  );
}
