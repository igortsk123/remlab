import type { Metadata } from "next";
import { TrialStatus } from "@/components/trial/TrialStatus";
import { TryShell } from "@/components/trial/TryShell";
import { textOf } from "@/lib/trial/i18n";
import { pageLang } from "@/lib/trial/page-lang";

// Задание пробы (план agent-trial-01, T-C): id в адресе — ключ ссылки, поэтому noindex и no-referrer (заголовки ответов —
// Caddy и `lib/trial/config.ts:TRIAL_HEADERS`). Всё живое — на клиенте: опрос статуса, по готовности геометрии — переход
// в тур `/try/<id>/tour/` (`TrialStatus`). Язык — `?lang=ru|en` (план agent-trial-08, П), его же получает тур.
type Search = Promise<{ lang?: string | string[] }>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const { meta } = textOf((await pageLang(await searchParams)).lang);
  return { title: meta.jobTitle, robots: { index: false, follow: false }, referrer: "no-referrer" };
}

export const dynamic = "force-dynamic";

export default async function TrialPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Search }) {
  const { id } = await params;
  const { lang, explicit } = await pageLang(await searchParams);
  return (
    <TryShell lang={lang} explicit={explicit} path={`/try/${encodeURIComponent(id)}`}>
      <TrialStatus id={id} lang={lang} />
    </TryShell>
  );
}
