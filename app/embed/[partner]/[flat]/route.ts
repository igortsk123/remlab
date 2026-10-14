// Встраивание демо на сайт застройщика: `/embed/<партнёр>/<квартира>` (план b2b-07, ADR-0283). Та же страница демо,
// но с разрешением показа рамкой только на доменах этого партнёра (`frame-ancestors`), режимом встраивания и
// квартирой из адреса. Квартира обязана принадлежать партнёру и иметь витрину (`sources.demoData`) — иначе 404.
import { readFile } from "node:fs/promises";

import { NextResponse } from "next/server";

import { embedCsp, injectEmbed } from "@/lib/embed/page";
import { findApartment, findPartner } from "@/lib/partners/registry";

const DEMO_FILE = process.env.DEMO_DIR ? `${process.env.DEMO_DIR}/index.html` : "/srv/demo/index.html";

export async function GET(req: Request, ctx: { params: Promise<{ partner: string; flat: string }> }): Promise<Response> {
  const { partner, flat } = await ctx.params;
  const p = findPartner(partner);
  const hit = p ? findApartment(flat, [p]) : null;
  if (!p || !hit || !hit.apartment.sources.demoData) return new NextResponse("not found", { status: 404 });
  let html: string;
  try {
    html = await readFile(DEMO_FILE, "utf8"); // витрина смонтирована в контейнер (docker-compose: ./demo:/srv/demo:ro)
  } catch {
    return new NextResponse("demo unavailable", { status: 503, headers: { "Retry-After": "60" } });
  }
  const lang = new URL(req.url).searchParams.get("lang") === "en" ? "en" : "ru";
  return new NextResponse(injectEmbed(html, { partner: p.id, flat: hit.apartment.id, lang }), {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": embedCsp(p.frameDomains ?? []),
      "Cache-Control": "no-store",
    },
  });
}
