// Редирект-слой (v0.4, ADR-0016): единственный путь наружу из сметы. Логирует клик
// (приоритет реф-регистраций) и 302 на реф-версию ссылки (из маршрутов) или прямую.

import { type NextRequest } from "next/server";
import { estimateRepo } from "@/modules/estimate/repository";
import { resolveTarget, domainFromUrl } from "@/lib/estimate/links";
import { readSessionId } from "@/lib/session";

// Location может быть относительным ("/") — так корректно за reverse-proxy (req.url — внутренний).
function redirect(location: string) {
  return new Response(null, { status: 302, headers: { Location: location } });
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ eid: string; iid: string }> }) {
  const { eid, iid } = await ctx.params;
  const repo = estimateRepo();
  const est = await repo.get(eid);
  const item = est?.items.find((i) => i.id === iid);
  if (!est || !item?.url) return redirect("/");

  const routes = await repo.activeRoutes();
  const target = resolveTarget(item.url, routes);
  const sessionId = await readSessionId();
  try {
    await repo.logClick({ estimateId: eid, itemId: iid, domain: domainFromUrl(item.url), targetUrl: target, sessionId });
  } catch {
    /* лог кликов — best-effort, не роняет переход */
  }
  return redirect(target); // item.url — абсолютный внешний адрес
}
