import { notFound } from "next/navigation";
import { repo } from "@/modules/store/repository";
import { saveStyle } from "@/app/actions";
import { Progress } from "@/components/Progress";
import { STYLE_CARDS } from "@/contracts/style";

export default async function StylePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await repo().get(id);
  if (!project) notFound();

  return (
    <main className="container">
      <Progress step={3} />
      <h1>Выберите визуальное направление</h1>
      <p className="muted">Отметьте 1–3 стиля, которые нравятся. Не обязательно проходить все.</p>

      <form action={saveStyle.bind(null, id)} className="stack">
        <div className="stack">
          {STYLE_CARDS.map((c) => (
            <label key={c.id} className="card" style={{ cursor: "pointer", padding: 16 }}>
              <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
                <input type="checkbox" name="liked" value={c.id} style={{ width: 18, height: 18 }} />
                <strong>{c.name}</strong>
              </div>
              <p className="muted" style={{ margin: "6px 0 0", fontSize: 14 }}>
                Акцент: {c.accent}. {c.note}
              </p>
            </label>
          ))}
        </div>
        <button className="btn btn-block" type="submit">Показать AI-превью</button>
      </form>
    </main>
  );
}
