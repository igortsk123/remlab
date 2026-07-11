"use server";

import { redirect } from "next/navigation";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { estimateRepo } from "@/modules/estimate/repository";
import { getSessionId } from "@/lib/session";
import { track } from "@/lib/analytics";
import { estimate as estimateSchema, estimateItem, type EstimateItem } from "@/contracts/estimate";
import { wallpaper, tile, paint, laminate, perimeter, wallArea } from "@/lib/estimate/calc";
import { CALC_META, COMPANIONS, type CalcKind } from "@/lib/estimate/companions";
import { domainFromUrl } from "@/lib/estimate/links";
import { estimateRemont, DEPTH_LABEL, REGION_LABEL, type Depth, type Region } from "@/lib/pricing/works";

function num(fd: FormData, k: string): number {
  const v = Number(String(fd.get(k) ?? "").replace(",", "."));
  return Number.isFinite(v) && v > 0 ? v : 0;
}
function str(fd: FormData, k: string): string {
  const v = fd.get(k);
  return typeof v === "string" ? v.trim() : "";
}

// Вход А: калькулятор материала → смета с одной расчётной позицией + сопутка.
export async function createFromCalc(kind: CalcKind, fd: FormData): Promise<void> {
  const width = num(fd, "width");
  const length = num(fd, "length");
  const height = num(fd, "height") || 2.7;
  const sessionId = await getSessionId();

  const title = CALC_META[kind].title;
  let calc = { qty: 0, unit: CALC_META[kind].unit, note: "" };
  if (kind === "oboi") calc = wallpaper({ perimeterM: perimeter(width, length), heightM: height });
  else if (kind === "plitka") calc = tile({ areaM2: num(fd, "area") || width * length });
  else if (kind === "kraska") calc = paint({ areaM2: wallArea(width, length, height) });
  else if (kind === "laminat") calc = laminate({ areaM2: num(fd, "area") || width * length });

  const main: EstimateItem = {
    id: randomUUID(), title, qty: calc.qty, unit: calc.unit, source: "calc", note: calc.note,
  };
  const companions: EstimateItem[] = COMPANIONS[kind].map((t) => ({
    id: randomUUID(), title: t, qty: 1, unit: "шт", source: "our_pick", note: "сопутствующее — не забудьте",
  }));

  const now = new Date().toISOString();
  const est = estimateSchema.parse({
    id: randomUUID(), sessionId, title: `Смета: ${title}`, source: "calc",
    items: [main, ...companions], meta: { kind, width, length, height }, createdAt: now, updatedAt: now,
  });
  await estimateRepo().create(est);
  await track("estimate_created", sessionId, { source: "calc", kind });
  redirect(`/e/${est.id}`);
}

// Вход Б: выбранный вариант бюджета → смета с позициями работ и материалов.
export async function createFromRemont(fd: FormData): Promise<void> {
  const area = num(fd, "area");
  const depth = (str(fd, "depth") || "update") as Depth;
  const region = (str(fd, "region") || "msk") as Region;
  const variantKey = str(fd, "variant") || "mid";
  const sessionId = await getSessionId();
  const variants = estimateRemont(area || 20, depth, region);
  const v = variants[variantKey as keyof typeof variants] ?? variants.mid;

  const items: EstimateItem[] = v.lines.map((l) => ({
    id: randomUUID(), title: l.title, qty: 1, unit: "работа/материал",
    unitPriceRub: l.rub, source: "our_pick" as const, note: l.kind === "work" ? "работа" : "материал",
  }));
  const now = new Date().toISOString();
  const est = estimateSchema.parse({
    id: randomUUID(), sessionId, title: `Ремонт ${area || 20} м² — ${v.label}`, source: "remont",
    items, meta: { area, depth, region, depthLabel: `${DEPTH_LABEL[depth]} · ${REGION_LABEL[region]}`, variant: v.key }, createdAt: now, updatedAt: now,
  });
  await estimateRepo().create(est);
  await track("estimate_created", sessionId, { source: "remont", variant: v.key });
  redirect(`/e/${est.id}`);
}

// Добавить свою ссылку (деградация из барьеров: название/цену вводит юзер, парс OG — позже).
export async function addLink(estimateId: string, fd: FormData): Promise<void> {
  const url = str(fd, "url");
  const parsed = z.string().url().safeParse(url);
  if (!parsed.success) redirect(`/e/${estimateId}?err=url`);
  const item = estimateItem.parse({
    id: randomUUID(),
    title: str(fd, "title") || domainFromUrl(url) || "Товар по ссылке",
    qty: num(fd, "qty") || 1,
    unit: str(fd, "unit") || "шт",
    unitPriceRub: num(fd, "price") || undefined,
    url, domain: domainFromUrl(url) ?? undefined, source: "user_link",
  });
  const cur = await estimateRepo().get(estimateId);
  if (!cur) redirect("/");
  await estimateRepo().update(estimateId, { items: [...cur!.items, item] });
  redirect(`/e/${estimateId}`);
}

export async function removeItem(estimateId: string, itemId: string): Promise<void> {
  const cur = await estimateRepo().get(estimateId);
  if (!cur) redirect("/");
  await estimateRepo().update(estimateId, { items: cur!.items.filter((i) => i.id !== itemId) });
  redirect(`/e/${estimateId}`);
}

// «Сохранить» = отметить намерение (смета уже в сессии); шлём цель и остаёмся на странице.
export async function markSaved(estimateId: string): Promise<void> {
  const sessionId = await getSessionId();
  await track("estimate_saved", sessionId, { estimateId });
  redirect(`/e/${estimateId}?saved=1`);
}
