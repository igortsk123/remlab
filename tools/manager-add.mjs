// Завести менеджера застройщика (план b2b-02) и получить ссылку на его страницу.
// Запуск на сервере (внутри контейнера приложения — там DATABASE_URL и драйвер):
//   docker exec -i remlab-app node --input-type=module - --partner demo --name "Анна" \
//     --phone "+7 913 000-00-00" --telegram anna_sales --whatsapp "+7 913 000-00-00" \
//     [--connect-phone "+7 913 …"] < tools/manager-add.mjs
// Повторный запуск с тем же --id обновляет контакты, ключ страницы не меняет (--rotate-key — новый).
import postgres from "postgres";
import { randomBytes } from "node:crypto";

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]?.startsWith("--") || all[i + 1] === undefined ? "1" : all[i + 1]]] : acc), []));
// та же нормализация, что `modules/sends/phone.ts`
function normalizePhone(raw) {
  let d = String(raw ?? "").replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("8")) d = `7${d.slice(1)}`;
  else if (d.length === 10 && d.startsWith("9")) d = `7${d}`;
  else if (d.length === 11 && d.startsWith("07")) d = `44${d.slice(1)}`;
  return d.length >= 11 && d.length <= 15 ? d : null;
}
if (!args.partner || !args.name) { console.error("нужны --partner и --name"); process.exit(1); }
const id = args.id || `${args.partner}-${randomBytes(4).toString("hex")}`;
const connect = normalizePhone(args["connect-phone"] || args.phone || "");
const wa = args.whatsapp ? normalizePhone(args.whatsapp) : null;
const key = randomBytes(16).toString("base64url");
const sql = postgres(process.env.DATABASE_URL, { max: 1 });
const [row] = await sql`
  insert into managers (id, partner_id, display_name, public_phone, public_telegram, public_whatsapp, connect_phone, page_key)
  values (${id}, ${args.partner}, ${args.name}, ${args.phone ?? null}, ${(args.telegram ?? "").replace(/^@/, "") || null}, ${wa}, ${connect}, ${key})
  on conflict (id) do update set display_name = excluded.display_name, public_phone = excluded.public_phone,
    public_telegram = excluded.public_telegram, public_whatsapp = excluded.public_whatsapp, connect_phone = excluded.connect_phone,
    page_key = case when ${args["rotate-key"] === "1"} then excluded.page_key else managers.page_key end
  returning id, page_key`;
await sql.end();
console.log(`менеджер ${row.id}: страница https://remont-lab.online/manager#${row.page_key}`);
console.log(connect ? `подключение к боту по номеру ${connect}` : "номер для бота не задан — бот его не узнает");
