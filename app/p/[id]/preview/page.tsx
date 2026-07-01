import Link from "next/link";
import { notFound } from "next/navigation";
import { repo } from "@/modules/store/repository";
import { Progress } from "@/components/Progress";
import { GenerateOnMount } from "@/components/GenerateOnMount";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;

export default async function PreviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await repo().get(id);
  if (!project) notFound();

  if (project.status !== "preview_ready" && project.status !== "paid") {
    return (
      <main className="container">
        <Progress step={4} />
        <GenerateOnMount projectId={id} />
      </main>
    );
  }

  const freeItems = project.items.filter((i) => !i.locked);
  const lockedCount = project.items.length - freeItems.length;

  return (
    <main className="container">
      <Progress step={4} />
      <h1>Ваша комната обновлённая</h1>

      {project.previewImage ? (
        <img className="preview" src={project.previewImage.dataUrl} alt="AI-превью комнаты" />
      ) : (
        <p className="note">Фото не приложено — показываем идеи и бюджет ниже.</p>
      )}
      <p className="note" style={{ marginTop: 12 }}>
        Это визуальная концепция вашей комнаты, а не рабочий проект. Перед покупкой проверьте размеры.
      </p>

      {project.analysis && (
        <div className="card stack" style={{ marginTop: 20 }}>
          <p className="eyebrow">AI понял комнату</p>
          <p style={{ margin: 0 }}>{project.analysis.summary}</p>
          <div className="row">
            {project.analysis.objects.map((o, i) => (
              <span key={i} className="chip" data-selected={o.action === "keep"}>
                {o.label} · {o.action === "keep" ? "оставляем" : "меняем"}
              </span>
            ))}
          </div>
        </div>
      )}

      <h2 style={{ marginTop: 28 }}>Идеи изменений</h2>
      <div className="stack">
        {project.ideas.map((idea, i) => (
          <div key={i} className="card">
            <strong>{idea.title}</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>{idea.detail}</p>
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 28 }}>Товары и материалы</h2>
      <p className="muted">Показано {freeItems.length} из {project.items.length}.</p>
      <div className="grid-cards">
        {project.items.map((it, i) => (
          <div key={i} className={`card ${it.locked ? "locked" : ""}`} style={{ padding: 14 }}>
            <p className="eyebrow" style={{ margin: 0 }}>{it.kind === "material" ? "материал" : "товар"} · {it.category}</p>
            <strong style={{ fontSize: 15 }}>{it.title}</strong>
            <p className="muted" style={{ margin: "4px 0 0" }}>{rub(it.priceRub)}</p>
          </div>
        ))}
      </div>

      {project.budget && (
        <div className="card" style={{ marginTop: 20 }}>
          <p className="eyebrow" style={{ margin: 0 }}>Примерный бюджет</p>
          <h2 style={{ margin: "6px 0" }}>{rub(project.budget.minRub)} – {rub(project.budget.maxRub)}</h2>
          <p className="muted" style={{ margin: 0 }}>Точность: {project.budget.confidence}. Уточним на полном плане.</p>
        </div>
      )}

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">В полном плане комнаты</p>
        <p style={{ margin: 0 }}>
          Ещё {lockedCount} позиций с ценами и ссылками, 3 альтернативы по ключевым, подробный бюджет,
          чек-лист замеров, пошаговый план и PDF — с сохранением в «Мои комнаты».
        </p>
        <Link className="btn btn-block" href={`/p/${id}/paywall`}>Открыть полный план</Link>
      </div>
    </main>
  );
}
