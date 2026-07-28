"use server";

import { z } from "zod";
import { headers } from "next/headers";
import { getSessionId } from "@/lib/session";
import { leadRepo } from "@/modules/leads/repository";
import { notifyAdminOfLead } from "@/lib/leads/router";
import { track } from "@/lib/analytics";

const schema = z.object({
  channel: z.enum(["email", "tg", "max"]),
  email: z.string().email().optional(),
  city: z.string().min(2).max(80),
  urls: z.array(z.string()).optional(),
  kind: z.string().optional(),
  consent: z.boolean(),
});

export type CaptureLeadResult = { ok: true; leadNo: number | null; startCode: string } | { ok: false };

// Заявка «найдём дешевле» (П7): канал (почта/TG/MAX) + город обязателен; для почты нужен e-mail.
// Сохраняем ТОЛЬКО по согласию (ПДн-interim; юр. часть — TODO, CLAUDE.md). Ссылки склеены в url.
// startCode — для deep-link в бот (/start <code> привязывает чат к заявке).
export async function captureLead(input: unknown): Promise<CaptureLeadResult> {
  const parsed = schema.safeParse(input);
  if (!parsed.success || !parsed.data.consent) return { ok: false };
  const { channel, email, urls, city, kind } = parsed.data;
  if (channel === "email" && !email) return { ok: false };

  const cleanUrls = (urls ?? []).map((u) => u.trim()).filter(Boolean);
  const url = cleanUrls.length ? cleanUrls.join("\n") : undefined;
  const sessionId = await getSessionId();
  // Регион по IP: пока сохраняем страну/регион из заголовков прокси, если есть (offline-geoip — П7b).
  const h = await headers();
  const ipRegion = h.get("x-vercel-ip-country-region") ?? h.get("x-geo-region") ?? undefined;

  const lead = await leadRepo().create({
    channel,
    email: email || undefined,
    url,
    city,
    kind: kind || undefined,
    sessionId,
    ipRegion,
  });
  await notifyAdminOfLead(lead); // карточка владельцу в служебный TG-бот (no-op без токена)
  await track("lead_captured", sessionId, { channel, urlCount: cleanUrls.length, city, kind: kind ?? "" });
  return { ok: true, leadNo: lead.leadNo, startCode: lead.id };
}
