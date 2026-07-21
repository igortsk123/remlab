import Link from "next/link";
import { estimateRepo } from "@/modules/estimate/repository";
import { repo } from "@/modules/store/repository";
import { readSessionId } from "@/lib/session";
import { plural } from "@/lib/format/plural";

export const metadata = {
  title: "Моя лаборатория — сохранённые сметы и дизайны",
  description: "Ваши сохранённые сметы и дизайны комнат в одном месте.",
};

export default async function LabPage() {
  const sid = await readSessionId();
  const estimates = sid ? await estimateRepo().listBySession(sid) : [];
  const rooms = sid ? await repo().listBySession(sid) : [];

  return (
    <main className="container">
      <p className="eyebrow">Моя лаборатория</p>
      <h1>Мои проекты ремонта</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Здесь собирается всё, что вы посчитали и придумали — сметы и дизайны комнат.
      </p>

      <div className="stack" style={{ marginTop: 20, gap: 12 }}>
        <Link className="card row" href="/estimates" style={{ textDecoration: "none", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ fontSize: 17 }}>📋 Мои сметы</strong>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 15 }}>
              {estimates.length > 0
                ? `${estimates.length} ${plural(estimates.length, "смета", "сметы", "смет")}`
                : "Пока пусто — соберите первую смету"}
            </p>
          </div>
          <span className="muted">→</span>
        </Link>

        <Link className="card row" href="/rooms" style={{ textDecoration: "none", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ fontSize: 17 }}>🛋️ Мои дизайны</strong>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 15 }}>
              {rooms.length > 0
                ? `${rooms.length} ${plural(rooms.length, "комната", "комнаты", "комнат")}`
                : "Пока пусто — покажем комнату в новом стиле"}
            </p>
          </div>
          <span className="muted">→</span>
        </Link>
      </div>

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">С чего начать</p>
        <div className="row">
          <Link className="btn" href="/calc">Посчитать материалы</Link>
          <Link className="btn btn-secondary" href="/start">Дизайн по фото</Link>
        </div>
      </div>
    </main>
  );
}
