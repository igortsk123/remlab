// Доступ к странице менеджера (план b2b-02): ключ 128 бит живёт во #фрагменте адреса (не уходит
// на сервер в адресе, не попадает в журнал Caddy и в Метрику), страница передаёт его заголовком.

import { TOKEN_RE } from "@/lib/token";
import { sendStore } from "@/modules/sends/service";
import type { Manager } from "@/modules/sends/types";

export async function managerFromRequest(req: Request): Promise<Manager | null> {
  const key = req.headers.get("x-manager-key") ?? "";
  if (!TOKEN_RE.test(key)) return null;
  return sendStore().managerByKey(key);
}
