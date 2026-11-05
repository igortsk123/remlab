// Имя для приветствия на странице менеджера (onb-03 Т2, ADR-0330 п.4): то же правило, что у страницы демо (блок QUIZNAME,
// `tools/ops/quiz-name.mjs`; совпадение сверяет `tests/unit/quiz-name.test.ts`). Имя живёт только в браузере менеджера и во
// #фрагменте ссылки — на сервер фрагмент не уходит.

/** 1–30 символов, только буквы, пробел и дефис, хотя бы одна буква; иначе пусто (цифры — похоже на телефон). */
export function cleanGreetName(s: string): string {
  const n = s.normalize("NFC").replace(/\s+/g, " ").trim();
  return n.length <= 30 && /^[\p{L}\- ]+$/u.test(n) && /\p{L}/u.test(n) ? n : "";
}

/** Ссылка с `#n=<имя>`; негодное или пустое имя — ссылка как была. Прежний `#n=` заменяется. */
export function linkWithName(url: string, name: string): string {
  const n = cleanGreetName(name);
  const [base = "", frag = ""] = url.split("#", 2);
  const rest = frag.split("&").filter((p) => p && !p.startsWith("n="));
  const parts = n ? [`n=${encodeURIComponent(n)}`, ...rest] : rest;
  return parts.length ? `${base}#${parts.join("&")}` : base;
}
