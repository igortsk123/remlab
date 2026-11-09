import type { Metadata } from "next";
import { TrialStatus } from "@/components/trial/TrialStatus";
import { TryShell } from "@/components/trial/TryShell";

// Задание пробы (план agent-trial-01, T-C): id в адресе — ключ ссылки, поэтому noindex и no-referrer (заголовки ответов —
// Caddy и `lib/trial/config.ts:TRIAL_HEADERS`). Всё живое — на клиенте: опрос статуса и серый тур (`TrialStatus`).
export const metadata: Metadata = {
  title: "Your tour · RemLab for Agents",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export const dynamic = "force-dynamic";

export default async function TrialPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <TryShell>
      <TrialStatus id={id} />
    </TryShell>
  );
}
