// Клиентский слой /lab/mesh-audit: сетевые вызовы отдельно от UI (code-standards).

import type { AuditItemView, BatchStateView, BatchView } from "./types";
import type { Verdict } from "./rules";

export type DecideOutcome = { kind: "ok"; item: AuditItemView } | { kind: "login" } | { kind: "error"; code?: string; message: string };

export async function sendDecision(item: Pick<AuditItemView, "id" | "generationKey">, verdict: Verdict): Promise<DecideOutcome> {
  try {
    const r = await fetch("/api/lab/mesh-audit/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: item.id, generationKey: item.generationKey, verdict, idemKey: `${item.generationKey}:${verdict}` }),
    });
    if (r.status === 401) return { kind: "login" };
    const data = (await r.json().catch(() => ({}))) as { item?: AuditItemView; error?: string; code?: string };
    if (!r.ok || !data.item) return { kind: "error", code: data.code, message: data.error ?? `HTTP ${r.status}` };
    return { kind: "ok", item: data.item };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "нет связи" };
  }
}

export async function cancelDecision(item: Pick<AuditItemView, "id" | "generationKey">): Promise<DecideOutcome> {
  try {
    const r = await fetch("/api/lab/mesh-audit/decisions", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: item.id, generationKey: item.generationKey }),
    });
    if (r.status === 401) return { kind: "login" };
    const data = (await r.json().catch(() => ({}))) as { item?: AuditItemView; error?: string; code?: string };
    if (!r.ok || !data.item) return { kind: "error", code: data.code, message: data.error ?? `HTTP ${r.status}` };
    return { kind: "ok", item: data.item };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "нет связи" };
  }
}

export async function loadBatchState(): Promise<BatchStateView | null> {
  try {
    const r = await fetch("/api/lab/mesh-audit/batch", { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as BatchStateView;
  } catch {
    return null;
  }
}

export async function requestBatch(batch: number): Promise<{ kind: "ok"; batch: BatchView } | { kind: "error"; message: string }> {
  try {
    const r = await fetch("/api/lab/mesh-audit/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch }),
    });
    const data = (await r.json().catch(() => ({}))) as { batch?: BatchView; error?: string };
    if (!r.ok || !data.batch) return { kind: "error", message: data.error ?? `HTTP ${r.status}` };
    return { kind: "ok", batch: data.batch };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "нет связи" };
  }
}

export async function markSeen(itemIds: number[]): Promise<void> {
  if (itemIds.length === 0) return;
  await fetch("/api/lab/mesh-audit/seen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ itemIds }),
  }).catch(() => undefined);
}
