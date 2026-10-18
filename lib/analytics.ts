// Лёгкая серверная аналитика/ошибки через PostHog (бесплатный тариф). Без ключа — no-op.
// PostHog free покрывает и события, и ошибки. Sentry (если захотим отдельно) добавим позже его SDK.
// Секрет — только POSTHOG_KEY в env; в код не зашивается.

import { headers } from "next/headers";

import { isLiveCheck } from "@/lib/http/live-check";

export type EventName =
  | "project_started"
  | "brief_completed"
  | "style_selected"
  | "preview_ready"
  | "paywall_viewed"
  | "pack_unlocked"
  | "cost_fake_door_viewed"
  | "problem_reported"
  | "estimate_created"
  | "estimate_saved"
  | "estimate_deleted"
  | "quiz_completed"
  | "lab_tab"
  | "viz_started"
  | "lead_captured"
  | "lead_replied"
  | "app_error";

type Props = Record<string, string | number | boolean | null>;

export async function track(event: EventName, distinctId: string, properties?: Props): Promise<void> {
  const key = process.env.POSTHOG_KEY;
  if (!key) return; // аналитика выключена, пока не задан ключ
  if (event !== "app_error" && (await fromLiveCheck())) return; // живая проверка прода — не человек; ошибки — нужны и от неё
  const host = process.env.POSTHOG_HOST ?? "https://eu.i.posthog.com";
  try {
    await fetch(`${host}/capture/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, event, distinct_id: distinctId, properties: properties ?? {} }),
    });
  } catch {
    // аналитика не должна ломать основной поток
  }
}

async function fromLiveCheck(): Promise<boolean> {
  try {
    return isLiveCheck(await headers());
  } catch {
    return false; // вне запроса (фон, крон) заголовков нет
  }
}

export async function captureError(err: unknown, context?: Props): Promise<void> {
  const message = err instanceof Error ? err.message : String(err);
  await track("app_error", "system", { message, ...(context ?? {}) });
}
