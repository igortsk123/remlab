import { notFound } from "next/navigation";

import { FlatConfigurator } from "@/components/flat3d/FlatConfigurator";
import { loadFlat3d } from "@/lib/configurator/data";
import { fromDemoVariant, type DemoData } from "@/lib/configurator/fromDemo";
import { readConfig } from "@/lib/configurator/repo";
import type { Lang } from "@/lib/configurator/i18n";

export const metadata = {
  title: "Соберите свою квартиру — RemLab",
  description:
    "Пройдитесь по квартире в 3D, выберите пол, кухню, встроенную технику и отделку санузла, посмотрите цену и сохраните подбор.",
  robots: { index: false, follow: false },
};

// Страница динамическая: по ?c=<id> открывается сохранённый подбор.
export const dynamic = "force-dynamic";

/** Данные витрины. Отказ сети/формата — не ошибка страницы: открываем обычную квартиру. */
async function loadDemoVariant(variantId: string) {
  const url = process.env.NEXT_PUBLIC_DEMO_DATA_URL ?? "https://remont-lab.online/demo/demo-data.json";
  try {
    const r = await fetch(url, { next: { revalidate: 300 } });
    if (!r.ok) return null;
    return fromDemoVariant((await r.json()) as DemoData, variantId);
  } catch {
    return null;
  }
}

export default async function FlatPage({
  searchParams,
}: {
  searchParams: Promise<{ c?: string; lang?: string; room?: string; demo?: string }>;
}) {
  const sp = await searchParams;
  // ВАРИАНТ С ВИТРИНЫ (13.10). `?demo=set16` открывает ТУ ЖЕ комнату и ТУ ЖЕ мебель, что человек
  // видит на карточке /demo. Данные берём живыми с витрины, а не копией: ночная пересборка меняет
  // наборы, и копия назавтра показала бы не то, что на странице.
  let fromDemo: ReturnType<typeof fromDemoVariant> = null;
  if (sp.demo) fromDemo = await loadDemoVariant(sp.demo);
  const base = loadFlat3d();
  const { apartment, catalogue } = fromDemo ?? base;
  const lang: Lang = sp.lang === "en" ? "en" : "ru";

  let initial = null;
  if (sp.c) {
    const saved = await readConfig(sp.c);
    if (!saved) notFound();
    initial = saved.configuration;
  }

  return (
    // ширина НЕ через `.container`: он рассчитан на чтение (узкая колонка), а конфигуратору
    // нужна вся ширина экрана под сцену
    <main className="mx-auto w-full px-3 py-4 sm:px-5" style={{ maxWidth: 1700 }}>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold text-primary">
          {lang === "en" ? apartment.titleEn : apartment.titleRu}
        </h1>
        <p className="text-sm text-tertiary">
          {lang === "en"
            ? "Walk through your future home and choose the finishes and furniture"
            : "Пройдитесь по будущей квартире и соберите отделку и мебель под себя"}
        </p>
        <a
          className="ml-auto text-sm text-secondary underline"
          href={`/flat?lang=${lang === "en" ? "ru" : "en"}${sp.c ? `&c=${sp.c}` : ""}`}
        >
          {lang === "en" ? "Русский" : "English"}
        </a>
      </div>
      <FlatConfigurator apartment={apartment} catalogue={catalogue} initialConfig={initial} lang={lang} />
    </main>
  );
}
