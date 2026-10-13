// Отчёт застройщику (план b2b-03, ADR-0265): чистая сборка из строк базы — без ввода-вывода, чтобы
// проверять тестами. Неделя — КОГОРТА ПО ДАТЕ ОТПРАВКИ ссылки (понедельник в часовом поясе застройщика):
// «отправлены на неделе; результат на дату отчёта». Шаги считаются по отправкам (есть ли событие), не по
// людям. Статус менеджера — текущий и взаимоисключающий (его можно исправлять), это не «дошли до».

import type { ManagerStatus } from "@/contracts/send";

export type ReportSend = { id: string; apartmentId: string; createdAt: Date; openedAt: Date | null; status: string };
export type ReportInput = {
  sends: ReportSend[];
  events: { sendId: string; kind: string }[];
  savedSendIds: string[]; // отправки, по которым сохранили коллекцию (из `collections`)
  counters: { day: string; apartmentId: string; kind: string; n: number }[];
  timezone: string;
  now: Date;
  /** Первая неделя окна (понедельник YYYY-MM-DD): более ранние отправки и счётчики не входят. */
  fromWeek?: string;
};

const ENGAGE = new Set(["variant_view", "item_swap", "manager_contact_click", "alternative_request", "flat3d_open"]);
const STATUSES: ManagerStatus[] = ["contacted", "meeting", "deal", "lost"];

export type FunnelRow = {
  week: string; apartmentId: string | null; fresh: boolean;
  sent: number; opened: number; engaged: number; saved: number; contactClick: number; flat3d: number;
  status: Record<ManagerStatus, number>;
};
export type DirectRow = { week: string; apartmentId: string; designerOpen: number; variantView: number; itemSwap: number; flat3dOpen: number };

/** Понедельник недели (YYYY-MM-DD) для момента `d` в поясе `tz`. */
export function weekOf(d: Date, tz: string): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", weekday: "short" })
    .formatToParts(d).map((x) => [x.type, x.value]));
  return mondayOf(`${p.year}-${p.month}-${p.day}`);
}

/** Первая неделя окна из `weeks` недель, включая текущую. */
export function firstWeek(now: Date, tz: string, weeks: number): string {
  const cur = new Date(`${weekOf(now, tz)}T00:00:00Z`);
  return new Date(cur.getTime() - (weeks - 1) * 7 * 86_400_000).toISOString().slice(0, 10);
}

/** Понедельник недели для календарной даты YYYY-MM-DD. */
export function mondayOf(day: string): string {
  const t = new Date(`${day}T00:00:00Z`);
  const back = (t.getUTCDay() + 6) % 7;
  return new Date(t.getTime() - back * 86_400_000).toISOString().slice(0, 10);
}

const emptyRow = (week: string, apartmentId: string | null, fresh: boolean): FunnelRow => ({
  week, apartmentId, fresh, sent: 0, opened: 0, engaged: 0, saved: 0, contactClick: 0, flat3d: 0,
  status: { contacted: 0, meeting: 0, deal: 0, lost: 0 },
});

export function buildReport(inp: ReportInput): { weeks: FunnelRow[]; byApartment: FunnelRow[]; total: FunnelRow; direct: DirectRow[] } {
  const kinds = new Map<string, Set<string>>();
  for (const e of inp.events) (kinds.get(e.sendId) ?? kinds.set(e.sendId, new Set()).get(e.sendId)!).add(e.kind);
  const saved = new Set(inp.savedSendIds);
  const thisWeek = weekOf(inp.now, inp.timezone);
  const weeks = new Map<string, FunnelRow>();
  const byApt = new Map<string, FunnelRow>();
  const total = emptyRow("", null, false);

  for (const s of inp.sends) {
    const w = weekOf(s.createdAt, inp.timezone);
    if (inp.fromWeek && w < inp.fromWeek) continue;
    const ks = kinds.get(s.id) ?? new Set<string>();
    const rows = [
      weeks.get(w) ?? weeks.set(w, emptyRow(w, null, w === thisWeek)).get(w)!,
      byApt.get(s.apartmentId) ?? byApt.set(s.apartmentId, emptyRow("", s.apartmentId, false)).get(s.apartmentId)!,
      total,
    ];
    for (const r of rows) {
      r.sent += 1;
      if (s.openedAt || ks.has("designer_open")) r.opened += 1;
      if ([...ks].some((k) => ENGAGE.has(k)) || saved.has(s.id)) r.engaged += 1;
      if (saved.has(s.id)) r.saved += 1;
      if (ks.has("manager_contact_click")) r.contactClick += 1;
      if (ks.has("flat3d_open")) r.flat3d += 1;
      if ((STATUSES as string[]).includes(s.status)) r.status[s.status as ManagerStatus] += 1;
    }
  }

  const direct = new Map<string, DirectRow>();
  for (const c of inp.counters) {
    const w = mondayOf(c.day);
    if (inp.fromWeek && w < inp.fromWeek) continue;
    const k = `${w}|${c.apartmentId}`;
    const r = direct.get(k) ?? direct.set(k, { week: w, apartmentId: c.apartmentId, designerOpen: 0, variantView: 0, itemSwap: 0, flat3dOpen: 0 }).get(k)!;
    if (c.kind === "designer_open") r.designerOpen += c.n;
    else if (c.kind === "variant_view") r.variantView += c.n;
    else if (c.kind === "item_swap") r.itemSwap += c.n;
    else if (c.kind === "flat3d_open") r.flat3dOpen += c.n;
  }

  const desc = <T extends { week: string }>(a: T, b: T) => b.week.localeCompare(a.week);
  return {
    weeks: [...weeks.values()].sort(desc),
    byApartment: [...byApt.values()].sort((a, b) => b.sent - a.sent),
    total,
    direct: [...direct.values()].sort((a, b) => desc(a, b) || a.apartmentId.localeCompare(b.apartmentId)),
  };
}
