import { NextResponse } from "next/server";
import { z } from "zod";

import { configuration } from "@/contracts/configurator";
import { guard } from "@/lib/ratelimit/http";
import { baseSnapshotOf } from "@/lib/configurator/fromDemo";
import { buildQuote, revisions } from "@/lib/configurator/quote";
import { resolveScene } from "@/lib/configurator/resolve";
import { saveConfig } from "@/lib/configurator/repo";
import { resolveCollectionFlat, resolveFlat } from "@/lib/configurator/source";
import { incentiveOf } from "@/lib/partners/registry";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Сохранение подбора покупателя. Квартиру, каталог и цену сервер пересобирает САМ по реестру
// застройщиков (`lib/configurator/source.ts`): клиенту верим только в выборе и перестановках —
// не в цене, не в застройщике, не в составе набора (b2b-06). Контакт НЕ принимаем (Codex 28.09).
const Body = z.object({ configuration });

export async function POST(req: Request): Promise<Response> {
  const limited = await guard(req, "flatConfig");
  if (limited) return limited;
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });

  const cfg = parsed.data.configuration;
  if (Object.keys(cfg.selections).length > 200) {
    return NextResponse.json({ error: "слишком большой подбор" }, { status: 400 });
  }
  // подбор из 3D коллекции — пересобираем ту же коллекцию, а не исходный набор витрины (verify 14.10)
  const flat = cfg.collectionId ? await resolveCollectionFlat(cfg.collectionId) : await resolveFlat(cfg.apartmentId, cfg.baseVariant);
  if (!flat.ok) {
    return flat.reason === "unavailable"
      ? NextResponse.json({ error: "витрина временно недоступна, попробуйте через минуту" }, { status: 503 })
      : NextResponse.json({ error: "неизвестная квартира" }, { status: 400 });
  }

  try {
    const { apartment, catalogue, hit } = flat;
    const trusted = {
      ...cfg,
      // выбор — каким его понял расчёт сцены: недопустимое откатилось к набору, группа стульев выровнена (Codex 15.10) —
      // иначе ссылка хранила бы одно, а смета считала другое
      selections: resolveScene(apartment, catalogue, cfg).selections,
      version: 3 as const,
      developerId: hit.partner.id,
      ...(cfg.baseVariant ? { baseSnapshot: baseSnapshotOf(apartment, catalogue) } : {}),
    };
    // снимок пакета на момент сохранения — для отчёта застройщику: сумма (как раньше) и, с demo-23, режим и лимиты бюджетов
    const inc = incentiveOf(hit);
    const quote = {
      ...buildQuote(apartment, catalogue, trusted),
      certificate: { amount: inc?.total ?? 0, share: hit.partner.certificateShare },
      ...(inc ? { incentive: { mode: inc.mode, limits: inc.limits } } : {}),
    };
    const id = await saveConfig({ configuration: trusted, quote, ...revisions(apartment, catalogue) });
    return NextResponse.json({ id, quote });
  } catch {
    return NextResponse.json({ error: "не удалось сохранить" }, { status: 500 });
  }
}
