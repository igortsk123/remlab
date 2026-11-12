// Разделы страницы проверки мешей (/lab/mesh-check, T-20261112-118): тип товара из роли каталога (`mesh_audit_items.role`,
// мост шлёт `products.cat_role`). Одна таблица на сервер и клиент; порядок разделов = порядок обхода («сначала все диваны,
// потом все кашпо…», владелец 12.11). Роль, которой нет в таблице, и пустая роль — раздел «Без типа»: карточка не теряется.

export interface Section {
  key: string;
  title: string;
  roles: readonly string[];
}

export const SECTIONS: readonly Section[] = [
  { key: "divan", title: "Диваны", roles: ["диван"] },
  { key: "kreslo", title: "Кресла", roles: ["кресло"] },
  { key: "stul", title: "Стулья", roles: ["стул"] },
  { key: "stolik", title: "Журнальные столики", roles: ["столик"] },
  { key: "stol", title: "Обеденные столы", roles: ["стол обеденный"] },
  { key: "tv", title: "Тумбы ТВ", roles: ["тв-тумба"] },
  { key: "komod", title: "Комоды", roles: ["комод"] },
  { key: "shkaf", title: "Шкафы, стеллажи, витрины", roles: ["шкаф", "стеллаж", "витрина", "стенка"] },
  { key: "puf", title: "Пуфы", roles: ["пуф"] },
  { key: "kashpo", title: "Кашпо", roles: ["кашпо"] },
  { key: "vaza", title: "Вазы", roles: ["ваза"] },
  { key: "svet", title: "Свет", roles: ["торшер", "лампа", "люстра"] },
  { key: "kamin", title: "Камины", roles: ["камин"] },
  { key: "other", title: "Без типа", roles: [] },
];

export const OTHER_SECTION = "other";

const BY_ROLE: ReadonlyMap<string, string> = new Map(SECTIONS.flatMap((s) => s.roles.map((r) => [r, s.key] as const)));

export function sectionOf(role: string | null | undefined): string {
  return (role && BY_ROLE.get(role.trim().toLowerCase())) || OTHER_SECTION;
}

/** Роли раздела для SQL-фильтра; у «Без типа» — null: фильтр «роль не из известных или пустая». */
export function rolesOf(key: string): readonly string[] | null {
  const s = SECTIONS.find((x) => x.key === key);
  return !s || s.key === OTHER_SECTION ? null : s.roles;
}

export const KNOWN_ROLES: readonly string[] = SECTIONS.flatMap((s) => s.roles);

export function sectionByKey(key: string | undefined): Section | undefined {
  return SECTIONS.find((s) => s.key === key);
}

export interface SectionCount {
  key: string;
  title: string;
  total: number;
  checked: number;
}

/** Счётчики «проверено N из M» по разделам из пар (роль, отмечена ли карточка по текущему поколению). Пустые разделы скрыты. */
export function countSections(rows: readonly { role: string | null; checked: boolean }[]): SectionCount[] {
  const acc = new Map<string, { total: number; checked: number }>();
  for (const r of rows) {
    const k = sectionOf(r.role);
    const a = acc.get(k) ?? { total: 0, checked: 0 };
    a.total += 1;
    if (r.checked) a.checked += 1;
    acc.set(k, a);
  }
  return SECTIONS.filter((s) => acc.has(s.key)).map((s) => ({ key: s.key, title: s.title, ...acc.get(s.key)! }));
}

/** Куда открыть страницу без выбора: первый раздел, где есть непроверенные («продолжить с места»); всё проверено — первый. */
export function firstOpenSection(counts: readonly SectionCount[]): string | undefined {
  return (counts.find((c) => c.checked < c.total) ?? counts[0])?.key;
}
