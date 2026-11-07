import { QUIZ_CHILD_RU, QUIZ_COLOUR_RU, QUIZ_HOUSEHOLD_RU, QUIZ_KIDS_RU, QUIZ_STYLE_RU } from "@/contracts/quiz";
import { cell, num, pct } from "@/components/partner/FunnelTable";
import type { QuizCount, QuizRow } from "@/modules/partner-report/quiz";

// Блок «Знакомство» отчёта застройщику (план onb-12, ADR-0265 + ADR-0330 п.4): только счётчики и доли по квартире, без людей.
// Подписи — словари `contracts/quiz.ts` (те же, что в сигнале менеджеру). Доля ответа — от прошедших опрос.
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const GROUPS: [string, (r: QuizRow) => QuizCount[], Record<string, string>][] = [
  ["Понравились гостиные", (r) => r.photo, QUIZ_STYLE_RU],
  ["Понравились спальни", (r) => r.bedroom, QUIZ_STYLE_RU],   // опрос по комнатам (home-mix-01)
  ["Показали в итоге", (r) => r.result, QUIZ_STYLE_RU],
  ["Выбрали в итоге", (r) => r.chosen, QUIZ_STYLE_RU],
  ["Кто будет жить", (r) => r.household, QUIZ_HOUSEHOLD_RU],
  ["Сколько детей", (r) => r.kids, QUIZ_KIDS_RU],
  ["Возраст детей", (r) => r.child, QUIZ_CHILD_RU],
  ["Цвета", (r) => r.colour, QUIZ_COLOUR_RU],
];

/** Строки «подпись · число · доля»; доля — от `base` (нет — без доли). */
function Rows({ items }: { items: [string, number, number | null][] }) {
  return items.map(([h, n, base]) => (
    <tr key={h}><td style={cell}>{h}</td><td style={num}><b>{n}</b></td><td style={num} className="text-tertiary">{base === null ? "" : pct(n, base)}</td></tr>
  ));
}

export function QuizBlock({ rows, apartment }: { rows: QuizRow[]; apartment: (id: string) => string }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <h2 style={{ margin: 0, fontSize: 18 }}>Знакомство: опрос на первом экране</h2>
      <p className="muted" style={{ margin: 0 }}>
        Действия, а не люди. Доля ответа — от прошедших опрос; ответов можно выбрать несколько, поэтому в сумме больше 100%.
      </p>
      {rows.map((r) => (
        <table key={r.apartmentId} style={{ borderCollapse: "collapse", width: "100%", fontSize: 15, tableLayout: "fixed" }}>
          <colgroup><col /><col style={{ width: 64 }} /><col style={{ width: 64 }} /></colgroup>   {/* колонки чисел — одни у всех квартир */}
          <tbody>
            {rows.length > 1 && <tr><td style={{ ...cell, paddingTop: 16 }} colSpan={3}><b>{apartment(r.apartmentId)}</b></td></tr>}
            <Rows items={[["Показали приветствие", r.open, null], ["Прошли до конца", r.done, r.open],
              ["Пропустили («Сразу к стилям»)", r.skip, r.open], ["Сменили стиль после опроса", r.styleChange, r.done]]} />
            {GROUPS.map(([h, f, dict]) => {
              const items = f(r);
              return items.some((c) => c.n > 0) ? [   // группа без единого ответа (например, детей нет) — не показываем
                <tr key={h}><td style={{ ...cell, paddingTop: 16 }} className="text-tertiary" colSpan={3}>{h}</td></tr>,
                <Rows key={`${h}-rows`} items={items.map((c) => [cap(dict[c.id] ?? c.id), c.n, r.done] as [string, number, number])} />,
              ] : null;
            })}
          </tbody>
        </table>
      ))}
    </div>
  );
}
