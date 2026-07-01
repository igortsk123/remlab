"use server";

import { redirect } from "next/navigation";
import { randomUUID } from "node:crypto";
import { repo } from "@/modules/store/repository";
import { getSessionId } from "@/lib/session";
import { project as projectSchema, briefSchema, type Photo } from "@/contracts/project";
import { styleProfile as styleProfileSchema, styleId, type StyleId } from "@/contracts/style";
import { roomType, goal, interventionLevel, budgetBand, keepItem, constraint } from "@/contracts/enums";

function str(fd: FormData, k: string): string | undefined {
  const v = fd.get(k);
  return typeof v === "string" && v.length ? v : undefined;
}
function many<T>(fd: FormData, k: string, parse: (v: string) => T | undefined): T[] {
  return fd.getAll(k).flatMap((v) => (typeof v === "string" ? [parse(v)] : [])).filter((x): x is T => x !== undefined);
}
function safe<T>(schema: { safeParse: (v: unknown) => { success: boolean; data?: T } }, v: unknown): T | undefined {
  const r = schema.safeParse(v);
  return r.success ? r.data : undefined;
}

export async function startProject(fd: FormData): Promise<void> {
  const g = safe(goal, str(fd, "goal")) ?? "refresh";
  if (g === "estimate_cost") redirect("/soon?f=cost");

  const sessionId = await getSessionId();
  const id = randomUUID();
  const now = new Date().toISOString();
  const rt = safe(roomType, str(fd, "roomType")) ?? "living_room";

  const record = projectSchema.parse({
    id, sessionId, status: "brief_done", createdAt: now, updatedAt: now,
    title: rt === "bedroom" ? "Спальня" : "Гостиная",
    brief: {
      roomType: rt, goal: g,
      interventionLevel: safe(interventionLevel, str(fd, "interventionLevel")) ?? "refresh",
    },
  });
  await repo().create(record);
  redirect(`/p/${id}/brief`);
}

async function fileToPhoto(fd: FormData): Promise<Photo | null> {
  const f = fd.get("photo");
  if (!(f instanceof File) || f.size === 0) return null;
  const base64 = Buffer.from(await f.arrayBuffer()).toString("base64");
  const mimeType = f.type || "image/jpeg";
  return { id: randomUUID(), mimeType, dataUrl: `data:${mimeType};base64,${base64}` };
}

export async function saveBrief(id: string, fd: FormData): Promise<void> {
  const brief = safe(briefSchema.partial(), {
    city: str(fd, "city") ?? "",
    budgetBand: safe(budgetBand, str(fd, "budgetBand")) ?? "unknown",
    keep: many(fd, "keep", (v) => safe(keepItem, v)),
    constraints: many(fd, "constraints", (v) => safe(constraint, v)),
  }) ?? {};
  const cur = await repo().get(id);
  const photo = await fileToPhoto(fd);
  await repo().update(id, {
    brief: { ...(cur?.brief ?? {}), ...brief },
    photos: photo ? [photo] : (cur?.photos ?? []),
  });
  redirect(`/p/${id}/style`);
}

export async function saveStyle(id: string, fd: FormData): Promise<void> {
  const liked = many<StyleId>(fd, "liked", (v) => safe(styleId, v));
  const profile = styleProfileSchema.parse({ selectedStyleIds: liked, likedStyleCards: liked });
  await repo().update(id, { styleProfile: profile, status: "style_done" });
  redirect(`/p/${id}/preview`);
}

export async function unlockPack(id: string): Promise<void> {
  await repo().update(id, { paid: true, status: "paid" });
  redirect(`/p/${id}/paywall`);
}
