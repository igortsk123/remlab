"use client";

import { useEffect, useState } from "react";
import { STYLE_CARDS } from "@/contracts/style";
import { SelectChips } from "@/components/SelectChips";

type Action = "keep" | "change" | "remove";
type Obj = { label: string; action: Action };

const ACTIONS: [Action, string][] = [["keep", "Оставить"], ["change", "Поменять"], ["remove", "Убрать"]];
const FALLBACK: Obj[] = [
  { label: "Стены", action: "change" },
  { label: "Пол", action: "keep" },
  { label: "Освещение", action: "change" },
  { label: "Текстиль и декор", action: "change" },
];

const inputStyle = {
  padding: "12px 14px", borderRadius: 10, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 16, fontFamily: "inherit",
} as const;

export function SelectRoom({
  id, thumb, initialObjects, initialStyles, action,
}: {
  id: string;
  thumb: string | null;
  initialObjects: Obj[] | null;
  initialStyles: string[];
  action: (fd: FormData) => void | Promise<void>;
}) {
  const [objects, setObjects] = useState<Obj[] | null>(initialObjects);
  const [loading, setLoading] = useState(!initialObjects);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (initialObjects) return;
    let alive = true;
    (async () => {
      setLoading(true); setError(false);
      try {
        const res = await fetch(`/api/p/${id}/analyze`, { method: "POST" });
        if (!res.ok) throw new Error("analyze failed");
        const data = await res.json();
        if (alive) setObjects(data.analysis?.objects?.length ? data.analysis.objects : FALLBACK);
      } catch {
        if (alive) { setError(true); setObjects(FALLBACK); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [id, initialObjects]);

  function setAction(i: number, a: Action) {
    setObjects((o) => (o ? o.map((x, idx) => (idx === i ? { ...x, action: a } : x)) : o));
  }

  if (loading) {
    return (
      <div className="stack center" style={{ padding: "48px 0" }}>
        <div style={{ fontSize: 40 }}>🔍</div>
        <h2>Анализируем фото…</h2>
        <p className="muted">Определяем предметы в вашей комнате</p>
      </div>
    );
  }

  return (
    <form action={action} className="stack">
      {thumb && (
        <img className="preview" src={thumb} alt="Ваше фото" style={{ maxHeight: 240, objectFit: "cover" }} />
      )}
      {error && (
        <p className="note">Не удалось точно распознать предметы — отметьте по общим зонам или опишите пожелание ниже.</p>
      )}

      <div className="stack">
        <label className="eyebrow">Предметы на фото</label>
        {(objects ?? []).map((o, i) => (
          <div key={i} className="card row" style={{ justifyContent: "space-between", alignItems: "center", padding: 12 }}>
            <strong style={{ fontSize: 15 }}>{o.label}</strong>
            <div className="row">
              {ACTIONS.map(([val, lbl]) => (
                <button key={val} type="button" className="chip" data-selected={o.action === val} onClick={() => setAction(i, val)}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="stack">
        <label className="eyebrow">Стиль (1–3)</label>
        <SelectChips name="liked" initial={initialStyles} options={STYLE_CARDS.map((c) => ({ value: c.id, label: c.name }))} />
      </div>

      <div className="stack">
        <label className="eyebrow">Ваши пожелания</label>
        <textarea
          name="wish"
          rows={3}
          placeholder="Опишите словами, что хотите: цвет стен, какую мебель поставить, общее настроение… Чем конкретнее — тем точнее результат."
          style={inputStyle}
        />
      </div>

      <input type="hidden" name="choices" value={JSON.stringify(objects ?? [])} />
      <button className="btn btn-block" type="submit">Сгенерировать комнату</button>
      <p className="note">Это визуальная концепция комнаты, а не рабочий проект. Размеры проверяйте перед покупкой.</p>
    </form>
  );
}
