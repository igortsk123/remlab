import type { FunnelRow } from "@/modules/partner-report/report";

// Таблица воронки по отправкам: каждая колонка — сколько ОТПРАВОК дошли до шага (не людей, не кликов).
const COLS: [string, (r: FunnelRow) => number][] = [
  ["Отправлено", (r) => r.sent],
  ["Открыли", (r) => r.opened],
  ["Выбирали мебель", (r) => r.engaged],
  ["Сохранили коллекцию", (r) => r.saved],
  ["Открыли 3D", (r) => r.flat3d],
  ["Нажали «консультация/ипотека»", (r) => r.contactClick],
  ["Связались", (r) => r.status.contacted],
  ["Встреча", (r) => r.status.meeting],
  ["Сделка", (r) => r.status.deal],
  ["Отказ", (r) => r.status.lost],
];

const pct = (n: number, of: number) => (of ? ` (${Math.round((n / of) * 100)}%)` : "");
const cell = { padding: "8px 10px", borderBottom: "1px solid var(--color-border-secondary)", textAlign: "right" as const, whiteSpace: "nowrap" as const };

export function FunnelTable({ rows, label }: { rows: { title: string; row: FunnelRow }[]; label: string }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
        <thead>
          <tr>
            <th style={{ ...cell, textAlign: "left" }}>{label}</th>
            {COLS.map(([h]) => <th key={h} style={{ ...cell, fontWeight: 500 }} className="text-tertiary">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ title, row }) => (
            <tr key={title}>
              <td style={{ ...cell, textAlign: "left" }}>{title}{row.fresh ? <span className="text-tertiary"> · неделя идёт</span> : null}</td>
              {COLS.map(([h, f], i) => <td key={h} style={cell}>{f(row)}{i > 0 && i < 6 ? <span className="text-tertiary">{pct(f(row), row.sent)}</span> : null}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
