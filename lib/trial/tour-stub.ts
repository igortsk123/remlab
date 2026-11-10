// Адрес тура `/try/<id>/tour/`, пока тур не открывается (T-20261110-07): человеку — короткая страница в цветах /try на его языке
// со ссылкой на страницу задания, а не голый текст «not ready». Машинным адресам (`version.json`, `demo-data.json`, файлы
// витрины) — по-прежнему текст (`lib/trial/tour.ts`).

import { textOf, type TrialLang } from "@/lib/trial/i18n";

/** wait — тур ещё готовится (задание идёт / страница не закрепилась); failed — задание закрыто без тура; missing / expired. */
export type StubKind = "wait" | "failed" | "missing" | "expired";
export type StubOpts = { lang: TrialLang; k?: string | null };

const esc = (s: string): string => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const KEY_RE = /^[A-Za-z0-9_-]{22}$/;

/** Страница задания `/try/<id>` с языком и ключом агента (ключ — только правильной формы). */
export function statusHref(id: string, o: StubOpts): string {
  const q = new URLSearchParams();
  if (o.k && KEY_RE.test(o.k)) q.set("k", o.k);
  q.set("lang", o.lang);
  return `/try/${encodeURIComponent(id)}?${q.toString()}`;
}

const CSS = `:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;
background:rgb(251 248 243);color:rgb(41 37 36);font:16px/1.5 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{width:100%;max-width:420px;background:#fff;border:1px solid rgb(231 229 228);border-radius:16px;padding:22px 20px;
box-shadow:0 1px 2px rgb(41 37 36/.06),0 4px 16px rgb(41 37 36/.06)}h1{font-size:20px;line-height:1.3;margin:0}
p{margin:8px 0 0;font-size:14px;color:rgb(87 83 78)}a{display:flex;align-items:center;justify-content:center;min-height:48px;
margin-top:12px;border-radius:12px;font-weight:600;text-decoration:none;border:1px solid rgb(176 106 74)}
a.p{background:rgb(176 106 74);color:#fff}a.p:hover{background:rgb(154 90 61)}a.s{color:rgb(154 90 61);background:#fff}`;

/** HTML страницы-заглушки; `self` — адрес самого тура (кнопка «Обновить»). */
export function stubHtml(kind: StubKind, id: string, self: string, o: StubOpts): string {
  const t = textOf(o.lang);
  const upload = `/try?lang=${o.lang}`;
  const [title, text, links]: [string, string, Array<[string, string, "p" | "s"]>] =
    kind === "wait" ? [t.tour.waitTitle, t.tour.waitText, [[self, t.tour.refresh, "p"], [statusHref(id, o), t.tour.progress, "s"]]]
      : kind === "failed" ? [t.msg.failedTitle, t.tour.failText, [[upload, t.msg.upload, "p"], [statusHref(id, o), t.tour.status, "s"]]]
        : kind === "expired" ? [t.msg.expiredTitle, t.msg.expiredText, [[upload, t.msg.upload, "p"]]]
          : [t.msg.missingTitle, t.msg.missingText, [[upload, t.msg.upload, "p"]]];
  const a = links.map(([href, label, c]) => `<a class="${c}" href="${esc(href)}">${esc(label)}</a>`).join("");
  return `<!doctype html><html lang="${o.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<meta name="robots" content="noindex,nofollow"><title>${esc(title)}</title><style>${CSS}</style></head>`
    + `<body><main role="status" data-stub="${kind}"><h1>${esc(title)}</h1><p>${esc(text)}</p>${a}</main></body></html>`;
}
