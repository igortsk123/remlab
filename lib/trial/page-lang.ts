// Язык страницы пробы на сервере (план agent-trial-08, П): `?lang=` из адреса, иначе язык браузера (Accept-Language),
// иначе язык рынка. `explicit` — язык задан адресом (тогда оболочке не нужен ранний скрипт сохранённого выбора).

import { headers } from "next/headers";
import { langFromAccept, parseLang, type TrialLang } from "@/lib/trial/i18n";

export async function pageLang(search: { lang?: string | string[] }): Promise<{ lang: TrialLang; explicit: boolean }> {
  const fromUrl = parseLang(Array.isArray(search.lang) ? search.lang[0] : search.lang);
  if (fromUrl) return { lang: fromUrl, explicit: true };
  return { lang: langFromAccept((await headers()).get("accept-language")), explicit: false };
}
