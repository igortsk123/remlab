import { notFound } from "next/navigation";

import { FlatConfigurator } from "@/components/flat3d/FlatConfigurator";
import { loadFlat3d } from "@/lib/configurator/data";
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

export default async function FlatPage({
  searchParams,
}: {
  searchParams: Promise<{ c?: string; lang?: string; room?: string }>;
}) {
  const sp = await searchParams;
  const { apartment, catalogue } = loadFlat3d();
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
