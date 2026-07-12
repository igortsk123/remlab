"use server";

import { z } from "zod";
import { getSessionId } from "@/lib/session";
import { leadRepo } from "@/modules/leads/repository";
import { track } from "@/lib/analytics";

const schema = z.object({
  email: z.string().email(),
  url: z.string().optional(),
  kind: z.string().optional(),
  consent: z.boolean(),
});

// Лид «найти дешевле»: сохраняем ТОЛЬКО по согласию (ПДн-interim; полноценная юр. часть — TODO, CLAUDE.md).
export async function captureLead(input: { email: string; url?: string; kind?: string; consent: boolean }): Promise<{ ok: boolean }> {
  const parsed = schema.safeParse(input);
  if (!parsed.success || !parsed.data.consent) return { ok: false };
  const { email, url, kind } = parsed.data;
  const sessionId = await getSessionId();
  await leadRepo().create({ email, channel: "email", url: url || undefined, kind: kind || undefined, sessionId });
  await track("lead_captured", sessionId, { channel: "email", hasUrl: Boolean(url), kind: kind ?? "" });
  return { ok: true };
}
