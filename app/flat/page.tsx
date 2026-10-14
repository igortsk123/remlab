import { notFound } from "next/navigation";

import { FlatConfigurator } from "@/components/flat3d/FlatConfigurator";
import { OpenBeacon } from "@/components/flat3d/OpenBeacon";
import type { Configuration } from "@/contracts/configurator";
import { baseSnapshotOf, staleSlots } from "@/lib/configurator/fromDemo";
import { readConfig } from "@/lib/configurator/repo";
import { defaultApartmentId, resolveFlat } from "@/lib/configurator/source";
import { apartmentCard } from "@/lib/partners/registry";
import type { Lang } from "@/lib/configurator/i18n";
import { TOKEN_RE } from "@/lib/token";

export const metadata = {
  title: "Соберите свою квартиру — RemLab",
  description:
    "Пройдитесь по квартире в 3D, выберите пол, кухню, встроенную технику и отделку санузла, посмотрите цену и сохраните подбор.",
  robots: { index: false, follow: false },
};

// Страница динамическая: по ?c=<id> открывается сохранённый подбор.
export const dynamic = "force-dynamic";

type Search = { c?: string; lang?: string; room?: string; demo?: string; flat?: string; s?: string };

/** Ссылка на ту же страницу с другим языком: все остальные параметры (`c`, `demo`, `flat`, `s`) сохраняются. */
function langHref(sp: Search, next: Lang): string {
  const q = new URLSearchParams(Object.entries(sp).filter(([, v]) => typeof v === "string") as [string, string][]);
  q.set("lang", next);
  return `/flat?${q.toString()}`;
}

export default async function FlatPage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const lang: Lang = sp.lang === "en" ? "en" : "ru";

  // СОХРАНЁННЫЙ ПОДБОР ЧИТАЕТСЯ ПЕРВЫМ (b2b-06): квартира и исходный набор — из него, а не из
  // адреса и не «базовая по умолчанию». Раньше `?c=` всегда открывал UK-квартиру.
  let saved: Configuration | null = null;
  if (sp.c) {
    const found = await readConfig(sp.c);
    if (!found) notFound();
    saved = found.configuration;
  }
  const apartmentId = saved?.apartmentId ?? sp.flat ?? defaultApartmentId(sp.demo ? "demo" : "flat3d");
  const baseVariant = saved ? saved.baseVariant : sp.demo;
  if (!apartmentId) notFound();

  let flat = await resolveFlat(apartmentId, baseVariant);
  // Набора из сохранения больше нет на витрине (ночная пересборка) — открываем ту же квартиру с
  // текущим набором и честно говорим об этом, а не 404 (verify 13.10).
  const variantGone = !flat.ok && flat.reason === "unknown" && !!saved?.baseVariant;
  if (variantGone) flat = await resolveFlat(apartmentId);
  if (!flat.ok) {
    if (flat.reason === "unknown") notFound();
    return (
      <main className="container" style={{ paddingTop: 32 }}>
        <p className="note">
          {lang === "en"
            ? "The showroom data is temporarily unavailable. Please try again in a minute."
            : "Данные витрины временно недоступны. Попробуйте через минуту."}
        </p>
      </main>
    );
  }
  const { apartment, catalogue, hit } = flat;

  // Набор витрины мог обновиться после сохранения: места, где модель сменилась, возвращаем к
  // текущему набору и говорим об этом прямо (ADR-0254 п.6 — не подменять молча).
  let initial = variantGone ? null : saved;
  let stale: string[] = [];
  if (!variantGone && saved?.baseSnapshot) {
    stale = staleSlots(saved, baseSnapshotOf(apartment, catalogue));
    if (stale.length) {
      const drop = <T,>(rec: Record<string, T>) => Object.fromEntries(Object.entries(rec).filter(([k]) => !stale.includes(k)));
      initial = { ...saved, selections: drop(saved.selections), placements: drop(saved.placements ?? {}) };
    }
  }
  const card = apartmentCard(hit, lang);

  return (
    // ширина НЕ через `.container`: он рассчитан на чтение (узкая колонка), а конфигуратору
    // нужна вся ширина экрана под сцену
    <main className="mx-auto w-full px-3 py-4 sm:px-5" style={{ maxWidth: 1700 }}>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold text-primary">
          {lang === "en" ? apartment.titleEn : apartment.titleRu}
        </h1>
        <p className="text-sm text-tertiary">{card.meta}</p>
        <a className="ml-auto text-sm text-secondary underline" href={langHref(sp, lang === "en" ? "ru" : "en")}>
          {lang === "en" ? "Русский" : "English"}
        </a>
      </div>
      {variantGone ? (
        <p className="note mb-3">
          {lang === "en"
            ? "The furniture set from this selection is no longer in the showroom — showing the current one."
            : "Набора мебели из этого подбора на витрине больше нет — показываем текущий."}
        </p>
      ) : null}
      {stale.length > 0 ? (
        <p className="note mb-3">
          {lang === "en"
            ? `The showroom set has changed since this selection was saved: ${stale.length} item(s) are shown from the current set.`
            : `С момента сохранения набор на витрине обновился: ${stale.length} предм. показаны из текущего набора.`}
        </p>
      ) : null}
      <OpenBeacon apartmentId={hit.apartment.id} sendId={sp.s && TOKEN_RE.test(sp.s) ? sp.s : null} lang={lang} />
      <FlatConfigurator
        apartment={apartment}
        catalogue={catalogue}
        initialConfig={initial}
        lang={lang}
        certificate={card.certificate ? { amount: card.certificate.amount } : null}
        facts={card.meta}
      />
    </main>
  );
}
