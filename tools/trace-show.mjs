// Разбор прогона по «номеру генерации»: краткий + подробный вид из БД.
// Запуск: pnpm trace <seq>  (с DATABASE_URL; на сервере — из /opt/remlab/.env).
// Печатает пути к файлам-ассетам (TRACE_DIR) — исходное/промежуточные/итоговое фото.

import postgres from "postgres";
import path from "node:path";

const seq = Number(process.argv[2]);
if (!Number.isInteger(seq)) {
  console.error("usage: pnpm trace <seq>");
  process.exit(1);
}
const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL не задан");
  process.exit(1);
}
const TRACE_DIR = process.env.TRACE_DIR || path.join(process.cwd(), ".data", "traces");
const ms = (n) => (n == null ? "—" : `${(n / 1000).toFixed(1)}с`);
const usd = (n) => (n == null ? "—" : `$${Number(n).toFixed(4)}`);

const sql = postgres(url, { max: 1 });
try {
  const [run] = await sql`select * from generation_runs where seq = ${seq} limit 1`;
  if (!run) {
    console.log(`Генерация #${seq} не найдена.`);
    process.exit(0);
  }
  const steps = await sql`select * from generation_steps where run_id = ${run.id} order by idx`;
  const assets = await sql`select * from generation_assets where run_id = ${run.id} order by created_at`;
  const byStep = (stepId) => assets.filter((a) => a.step_id === stepId);

  // ── КРАТКО ──────────────────────────────────────────────────────────
  console.log(`\n═══ ГЕНЕРАЦИЯ #${seq} — КРАТКО ═══`);
  console.log(`Пайплайн: ${run.pipeline_id} ${run.pipeline_version} · статус: ${run.status}` +
    `${run.error ? ` (${run.error})` : ""}`);
  console.log(`Итого: ${ms(run.total_latency_ms)} · ${usd(run.total_cost_usd)} · шагов: ${steps.length}`);
  const path_ = steps.map((s) => `${s.step_name}[${s.model}${s.status === "error" ? " ✗" : ""}]`).join(" → ");
  console.log(`Путь: ${path_ || "—"}`);
  const inputA = assets.find((a) => a.role === "input");
  const outputA = [...assets].reverse().find((a) => a.role === "output");
  if (inputA) console.log(`Исходное фото:  ${path.join(TRACE_DIR, inputA.storage_key)}`);
  if (outputA) console.log(`Итоговое фото:  ${path.join(TRACE_DIR, outputA.storage_key)}`);

  // ── ПОДРОБНО ────────────────────────────────────────────────────────
  console.log(`\n═══ ГЕНЕРАЦИЯ #${seq} — ПОДРОБНО ═══`);
  console.log(`run_id: ${run.id}`);
  console.log(`project: ${run.project_id ?? "—"} · session: ${run.session_id ?? "—"}`);
  console.log(`начат: ${run.started_at?.toISOString?.() ?? run.started_at} · завершён: ${run.finished_at?.toISOString?.() ?? run.finished_at ?? "—"}`);
  if (run.meta) console.log(`meta: ${JSON.stringify(run.meta)}`);
  for (const s of steps) {
    console.log(`\n─ Шаг ${s.idx + 1}: ${s.step_name} (${s.kind}) ─`);
    console.log(`  модель: ${s.provider}/${s.model} · статус: ${s.status}${s.error_kind ? ` [${s.error_kind}: ${s.error_message}]` : ""}`);
    console.log(`  время: ${ms(s.latency_ms)} · стоимость: ${usd(s.cost_usd)}`);
    if (s.prompt_id) console.log(`  промпт: ${s.prompt_id} ${s.prompt_version ?? ""}`);
    if (s.params) console.log(`  настройки: ${JSON.stringify(s.params)}`);
    if (s.prompt_text) console.log(`  текст промпта:\n    ${String(s.prompt_text).replace(/\n/g, "\n    ")}`);
    if (s.output_text) {
      const t = String(s.output_text);
      console.log(`  ответ: ${t.length > 600 ? t.slice(0, 600) + "…" : t}`);
    }
    for (const a of byStep(s.id)) {
      console.log(`  ${a.role} фото: ${path.join(TRACE_DIR, a.storage_key)} (${a.mime_type}, ${a.size_bytes ?? "?"}б)`);
    }
  }
  console.log("");
} finally {
  await sql.end();
}
