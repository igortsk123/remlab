import type { FunnelRow } from "@/modules/partner-report/report";

// Воронка по отправкам: каждая цифра — сколько ОТПРАВОК ссылок дошли до шага (не людей, не кликов).
// Итог — списком шагов (читается на телефоне), недели и квартиры — короткой таблицей из главных шагов.
const STEPS: [string, (r: FunnelRow) => number][] = [
  ["Менеджеры отправили ссылок", (r) => r.sent],
  ["Покупатель открыл", (r) => r.opened],
  ["Выбирал мебель или смотрел 3D", (r) => r.engaged],
  ["Сохранил свою коллекцию", (r) => r.saved],
  ["Открыл квартиру в 3D", (r) => r.flat3d],
  ["Нажал «консультация» или «ипотека»", (r) => r.contactClick],
];
const STATUS: [string, (r: FunnelRow) => number][] = [
  ["Связались", (r) => r.status.contacted],
  ["Встреча", (r) => r.status.meeting],
  ["Сделка", (r) => r.status.deal],
  ["Отказ", (r) => r.status.lost],
];
const SHORT: [string, (r: FunnelRow) => number][] = [
  ["Отправлено", (r) => r.sent], ["Открыли", (r) => r.opened], ["Выбирали", (r) => r.engaged],
  ["Обратились", (r) => r.contactClick], ["Сделка", (r) => r.status.deal],
];

const pct = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : "");
const cell = { padding: "8px 10px", borderBottom: "1px solid var(--color-border-secondary)" };
const num = { ...cell, textAlign: "right" as const, whiteSpace: "nowrap" as const };

export function StepList({ row }: { row: FunnelRow }) {
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 15 }}>
      <tbody>
        {STEPS.map(([h, f], i) => (
          <tr key={h}>
            <td style={cell}>{h}</td>
            <td style={num}><b>{f(row)}</b></td>
            <td style={num} className="text-tertiary">{i > 0 ? pct(f(row), row.sent) : ""}</td>
          </tr>
        ))}
        <tr><td style={{ ...cell, paddingTop: 16 }} className="text-tertiary" colSpan={3}>Статус, который поставил менеджер (текущий)</td></tr>
        {STATUS.map(([h, f]) => (
          <tr key={h}><td style={cell}>{h}</td><td style={num}><b>{f(row)}</b></td><td style={num} className="text-tertiary">{pct(f(row), row.sent)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export function ShortTable({ rows, label }: { rows: { title: string; row: FunnelRow }[]; label: string }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
        <thead>
          <tr>
            <th style={{ ...cell, textAlign: "left" }}>{label}</th>
            {SHORT.map(([h]) => <th key={h} style={{ ...num, fontWeight: 500 }} className="text-tertiary">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ title, row }) => (
            <tr key={title}>
              <td style={cell}>{title}{row.fresh ? <span className="text-tertiary"> · идёт</span> : null}</td>
              {SHORT.map(([h, f]) => <td key={h} style={num}>{f(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
