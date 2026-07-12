import Link from "next/link";
import { estimateRepo } from "@/modules/estimate/repository";
import { estimateTotal } from "@/contracts/estimate";
import { readSessionId } from "@/lib/session";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;

export default async function EstimatesPage() {
  const sid = await readSessionId();
  const list = sid ? await estimateRepo().listBySession(sid) : [];

  return (
    <main className="container">
      <h1>Мои сметы</h1>

      {list.length === 0 ? (
        <div className="card stack">
          <p style={{ margin: 0 }}>Пока пусто. Посчитайте материалы или бюджет ремонта — смета сохранится здесь и по постоянной ссылке.</p>
          <div className="row">
            <Link className="btn" href="/calc">Посчитать материалы</Link>
            <Link className="btn btn-secondary" href="/calc/remont">Стоимость ремонта</Link>
          </div>
        </div>
      ) : (
        <div className="stack">
          {list.map((e) => {
            const total = estimateTotal(e);
            return (
              <Link key={e.id} href={`/e/${e.id}`} className="card row" style={{ justifyContent: "space-between", textDecoration: "none", alignItems: "center" }}>
                <div>
                  <strong>{e.title}</strong>
                  <p className="muted" style={{ margin: "2px 0 0", fontSize: 14 }}>{e.items.length} позиций{total ? ` · ${rub(total)}` : ""}</p>
                </div>
                <span className="muted">→</span>
              </Link>
            );
          })}
        </div>
      )}

      <p style={{ marginTop: 24 }}><Link className="muted" href="/">← На главную</Link></p>
    </main>
  );
}
