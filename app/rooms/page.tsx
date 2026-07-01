import Link from "next/link";
import { repo } from "@/modules/store/repository";
import { readSessionId } from "@/lib/session";

const STATUS_LABEL: Record<string, string> = {
  started: "начато", brief_done: "бриф заполнен", style_done: "стиль выбран",
  preview_ready: "превью готово", paid: "полный план",
};

export default async function RoomsPage() {
  const sessionId = await readSessionId();
  const projects = sessionId ? await repo().listBySession(sessionId) : [];

  return (
    <main className="container">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>Мои комнаты</h1>
        <Link className="btn" href="/start">Добавить комнату</Link>
      </div>

      {projects.length === 0 ? (
        <div className="card center stack" style={{ marginTop: 24 }}>
          <div style={{ fontSize: 36 }}>🛋️</div>
          <p className="muted" style={{ margin: 0 }}>Пока пусто. Обновите первую комнату.</p>
          <Link className="btn" href="/start">Начать</Link>
        </div>
      ) : (
        <div className="stack" style={{ marginTop: 20 }}>
          {projects.map((p) => {
            const href = p.status === "preview_ready" || p.status === "paid"
              ? `/p/${p.id}/preview`
              : `/p/${p.id}/brief`;
            return (
              <Link key={p.id} href={href} className="card" style={{ textDecoration: "none" }}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <div className="row" style={{ gap: 12, alignItems: "center" }}>
                    {p.previewImage && (
                      <img src={p.previewImage.dataUrl} alt="" style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 10 }} />
                    )}
                    <div>
                      <strong>{p.title}</strong>
                      <p className="muted" style={{ margin: 0, fontSize: 14 }}>{STATUS_LABEL[p.status] ?? p.status}</p>
                    </div>
                  </div>
                  <span aria-hidden>→</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </main>
  );
}
