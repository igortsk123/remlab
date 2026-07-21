"use server";

import { z } from "zod";
import { getSessionId } from "@/lib/session";
import { leadRepo } from "@/modules/leads/repository";
import { track } from "@/lib/analytics";

const schema = z.object({
  email: z.string().email(),
  urls: z.array(z.string()).optional(),
  city: z.string().optional(),
  kind: z.string().optional(),
  consent: z.boolean(),
});

// Лид «найти выгоднее»: сохраняем ТОЛЬКО по согласию (ПДн-interim; полноценная юр. часть — TODO, CLAUDE.md).
// Несколько ссылок на товар храним склеенными в url (по строке на ссылку); город — отдельным полем.
export async function captureLead(input: { email: string; urls?: string[]; city?: string; kind?: string; consent: boolean }): Promise<{ ok: boolean }> {
  const parsed = schema.safeParse(input);
  if (!parsed.success || !parsed.data.consent) return { ok: false };
  const { email, urls, city, kind } = parsed.data;
  const cleanUrls = (urls ?? []).map((u) => u.trim()).filter(Boolean);
  const url = cleanUrls.length ? cleanUrls.join("\n") : undefined;
  const sessionId = await getSessionId();
  await leadRepo().create({ email, channel: "email", url, city: city || undefined, kind: kind || undefined, sessionId });
  await track("lead_captured", sessionId, { channel: "email", urlCount: cleanUrls.length, hasCity: Boolean(city), kind: kind ?? "" });
  return { ok: true };
}
