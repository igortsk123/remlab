import Link from "next/link";
import { estimateTotal, type Estimate } from "@/contracts/estimate";
import { estimateLabel } from "@/lib/estimate/label";
import { DeleteEstimateButton } from "@/components/lab/DeleteEstimateButton";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

// Список сохранённых расчётов (вид · дата · сумма → смета /e/<id>) — общий для вкладок лаборатории.
export function EstimateRows({ estimates }: { estimates: Estimate[] }) {
  return (
    <>
      {estimates.map((e) => {
        const total = estimateTotal(e);
        return (
          <div key={e.id} className="card row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            {/* Стрелка — сразу после названия (открыть), крестик — отдельно у правого края (удалить). */}
            <Link href={`/e/${e.id}`} style={{ textDecoration: "none", color: "inherit", flex: 1 }}>
              <strong style={{ fontSize: 16 }}>
                {estimateLabel(e)}
                <span aria-hidden style={{ color: "var(--color-fg-brand-primary)", fontSize: 19, marginLeft: 8, verticalAlign: "-1px" }}>→</span>
              </strong>
              <p className="muted" style={{ margin: "2px 0 0", fontSize: 14 }}>
                {fmtDate(e.createdAt)}
                {total > 0 ? ` · ~${rub(total)}` : ""}
              </p>
            </Link>
            <DeleteEstimateButton estimateId={e.id} label={estimateLabel(e)} />
          </div>
        );
      })}
    </>
  );
}
