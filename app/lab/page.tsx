import Link from "next/link";
import { estimateRepo } from "@/modules/estimate/repository";
import { repo } from "@/modules/store/repository";
import { readSessionId } from "@/lib/session";
import { estimateTotal, type Estimate } from "@/contracts/estimate";
import { CALC_META, type CalcKind } from "@/lib/estimate/companions";
import { DeleteEstimateButton } from "@/components/lab/DeleteEstimateButton";
import { plural } from "@/lib/format/plural";

export const metadata = {
  title: "Моя лаборатория: сохранённые расчёты и сметы",
  description: "Ваши сохранённые расчёты материалов и сметы в одном месте.",
};

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;

// Подпись расчёта: по виду материала из meta.kind («Расчёт обоев»), фолбэк — title сметы.
function estimateLabel(e: Estimate): string {
  const kind = (e.meta as { kind?: string } | undefined)?.kind as CalcKind | undefined;
  return kind && CALC_META[kind] ? `Расчёт ${CALC_META[kind].titleGen}` : e.title;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

// Центр сохранений: список расчётов сессии (вид · дата · сумма → смета /e/<id>).
export default async function LabPage() {
  const sid = await readSessionId();
  const estimates = sid ? await estimateRepo().listBySession(sid) : [];
  const rooms = sid ? await repo().listBySession(sid) : [];

  return (
    <main className="container">
      <p className="eyebrow">Моя лаборатория</p>
      <h1>Мои расчёты</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Здесь собирается всё, что вы посчитали: откройте расчёт, дополните ссылками и покупайте по списку.
      </p>

      {estimates.length === 0 ? (
        <div className="card stack" style={{ marginTop: 20 }}>
          <p style={{ margin: 0 }}>Пока пусто. Посчитайте материалы — расчёт сохранится сюда.</p>
          <Link className="btn" href="/calc">Посчитать материалы</Link>
        </div>
      ) : (
        <div className="stack" style={{ marginTop: 20, gap: 12 }}>
          {estimates.map((e) => {
            const total = estimateTotal(e);
            return (
              <div key={e.id} className="card row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <Link href={`/e/${e.id}`} className="row" style={{ textDecoration: "none", color: "inherit", flex: 1, justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <strong style={{ fontSize: 16 }}>{estimateLabel(e)}</strong>
                    <p className="muted" style={{ margin: "2px 0 0", fontSize: 14 }}>
                      {fmtDate(e.createdAt)}
                      {total > 0 ? ` · ~${rub(total)}` : ""}
                    </p>
                  </div>
                  <span className="muted">→</span>
                </Link>
                <DeleteEstimateButton estimateId={e.id} label={estimateLabel(e)} />
              </div>
            );
          })}
          <Link className="btn btn-secondary" href="/calc" style={{ alignSelf: "flex-start" }}>+ Новый расчёт</Link>
        </div>
      )}

      {rooms.length > 0 && (
        <p className="muted" style={{ marginTop: 24, fontSize: 14 }}>
          🛋️ <Link href="/rooms">Мои дизайны</Link>: {rooms.length} {plural(rooms.length, "комната", "комнаты", "комнат")}
        </p>
      )}
    </main>
  );
}
