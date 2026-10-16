import { notFound } from "next/navigation";

import { FlatConfigurator } from "@/components/flat3d/FlatConfigurator";
import { OpenBeacon } from "@/components/flat3d/OpenBeacon";
import type { Configuration } from "@/contracts/configurator";
import { baseSnapshotOf, staleSlots } from "@/lib/configurator/fromDemo";
import { readConfig } from "@/lib/configurator/repo";
import { defaultConfiguration } from "@/lib/configurator/resolve";
import { defaultApartmentId, resolveCollectionFlat, resolveFlat } from "@/lib/configurator/source";
import { apartmentCard, money } from "@/lib/partners/registry";
import type { Lang } from "@/lib/configurator/i18n";
import { TOKEN_RE } from "@/lib/token";
import { publicCard } from "@/modules/sends/service";

export const metadata = {
  title: "Соберите свою квартиру — RemLab",
  description:
    "Пройдитесь по квартире в 3D, выберите пол, кухню, встроенную технику и отделку санузла, посмотрите цену и сохраните подбор.",
  robots: { index: false, follow: false },
};

// Страница динамическая: по ?c=<id> открывается сохранённый подбор.
export const dynamic = "force-dynamic";

type Search = { c?: string; coll?: string; lang?: string; room?: string; demo?: string; flat?: string; s?: string };

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

  // КОЛЛЕКЦИЯ ПОКУПАТЕЛЯ (`?coll=`, b2b-05): расстановка и товары из неё, квартира — её же
  const fromColl = saved?.collectionId ?? (!saved && sp.coll && TOKEN_RE.test(sp.coll) ? sp.coll : null);
  let flat = fromColl ? await resolveCollectionFlat(fromColl) : await resolveFlat(apartmentId, baseVariant);
  // Набора из сохранения больше нет на витрине (ночная пересборка) — открываем ту же квартиру с
  // текущим набором и честно говорим об этом, а не 404 (verify 13.10).
  // устаревший номер варианта (пересборка витрины) открывает текущий вариант того же стиля — `resolveFlat.replaced`
  const replaced = flat.ok ? flat.replaced : undefined;
  const variantGone = (!flat.ok && flat.reason === "unknown" && !!saved?.baseVariant) || (!!replaced && !!saved);
  if (variantGone && !fromColl && !flat.ok) flat = await resolveFlat(apartmentId);
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
    // обновился один стул группы — сбрасываем всю группу (иначе группа откроется разной), и снимаем «убрано» (Codex 15.10)
    const groups = new Set(apartment.slots.filter((s) => stale.includes(s.id) && s.selectionGroup).map((s) => s.selectionGroup));
    stale = [...new Set([...stale, ...apartment.slots.filter((s) => s.selectionGroup && groups.has(s.selectionGroup)).map((s) => s.id)])];
    if (stale.length) {
      const drop = <T,>(rec: Record<string, T>) => Object.fromEntries(Object.entries(rec).filter(([k]) => !stale.includes(k)));
      initial = { ...saved, selections: drop(saved.selections), placements: drop(saved.placements ?? {}),
        ...(saved.hidden ? { hidden: saved.hidden.filter((id) => !stale.includes(id)) } : {}) };
    }
  }
  // открыт из коллекции — номер коллекции едет в подбор, чтобы сохранённая ссылка открывала ту же расстановку
  if (!saved && fromColl) initial = { ...defaultConfiguration(apartment, catalogue), collectionId: fromColl };
  const card = apartmentCard(hit, lang);
  // ШАПКА ПОКУПАТЕЛЯ (demo-05 п.7, разбор Codex 15.10): по ссылке менеджера (`s`), из окна демо (`demo`), по сохранённому
  // подбору (`c`) или коллекции (`coll`) покупатель видит квартиру застройщика, а не сайт remont-lab с пунктами «скоро».
  // Параметры только переключают вид — их значения на страницу не выводятся; ЖК, квартира, сертификат и менеджер — из
  // реестра и базы. `partner`/`embed` не включают вид: их никто не создаёт, а встраивание — свой маршрут `/embed/…`
  const buyer = [sp.s, sp.demo, sp.c, sp.coll].some((x) => x !== undefined);
  const rawSend = sp.s && TOKEN_RE.test(sp.s) ? sp.s : null;
  // ССЫЛКА МЕНЕДЖЕРА ДРУГОЙ КВАРТИРЫ НЕ УХОДИТ В 3D (P0 Codex): иначе клиент грузил контакты чужого менеджера и писал события
  // в чужую отправку. Неизвестную/отозванную ссылку отвергают сами API отправок (`/api/sends/…`) — её пропуск ничего не
  // открывает; база недоступна — тоже пропускаем (API проверит сам)
  let mgr: Awaited<ReturnType<typeof publicCard>> = null;
  let checked = true;
  if (rawSend) {
    try {
      mgr = await publicCard(rawSend);
    } catch {
      checked = false;
    }
  }
  const sendId = !rawSend ? null : checked && mgr && mgr.apartmentId !== hit.apartment.id ? null : rawSend;
  const manager = sendId && mgr ? mgr.manager.name : null;
  const cert = card.certificate ? money(card.certificate.amount, card.currency, lang) : null;

  return (
    // ширина НЕ через `.container`: он рассчитан на чтение (узкая колонка), а конфигуратору
    // нужна вся ширина экрана под сцену
    <main className="mx-auto w-full px-3 py-4 sm:px-5" style={{ maxWidth: 1700 }}>
      {/* высота шапки 0 сразу, до гидрации: липкие элементы иначе сначала встают под пустые 56 px */}
      {buyer ? <style>{".site-header{display:none}:root{--site-header-h:0px}"}</style> : null}
      {buyer ? (
        <p className="mb-1 flex flex-wrap gap-x-2 text-xs text-secondary sm:text-sm">
          <span className="font-medium text-primary">{card.complex}</span>
          <span>· {card.kind}{card.number ? ` № ${card.number}` : ""}</span>
          {cert ? <span>· {lang === "en" ? `allowance up to ${cert}` : `сертификат до ${cert}`}</span> : null}
          {manager ? <span>· {lang === "en" ? `your manager: ${manager}` : `ваш менеджер: ${manager}`}</span> : null}
        </p>
      ) : null}
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-lg font-semibold text-primary sm:text-xl">
          {lang === "en" ? apartment.titleEn : apartment.titleRu}
        </h1>
        {/* у покупателя ЖК уже в строке застройщика — повтор на телефоне съедал полэкрана (п.8) */}
        <p className={`text-sm text-tertiary${buyer ? " hidden sm:block" : ""}`}>{card.meta}</p>
        <a className="ml-auto text-sm text-secondary underline" href={langHref(sp, lang === "en" ? "ru" : "en")}>
          {lang === "en" ? "Русский" : "English"}
        </a>
      </div>
      {replaced && !saved ? (
        <p className="note mb-3">
          {lang === "en"
            ? "This layout has been updated — showing the current one" + (replaced.style ? " in the same style." : ".")
            : "Эта расстановка обновилась — показываем текущую" + (replaced.style ? ` в том же стиле (${replaced.style}).` : ".")}{" "}
          <a className="underline" href="/demo/">{lang === "en" ? "All layouts" : "Все расстановки"}</a>
        </p>
      ) : null}
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
      <OpenBeacon apartmentId={hit.apartment.id} sendId={sendId} lang={lang} />
      <FlatConfigurator
        apartment={apartment}
        catalogue={catalogue}
        initialConfig={initial}
        lang={lang}
        certificate={card.certificate ? { amount: card.certificate.amount } : null}
        facts={card.meta}
        sendId={sendId}
        logo={hit.partner.logoUrl}
      />
      {buyer ? <p className="mt-4 text-center text-xs text-quaternary">{lang === "en" ? "powered by remont-lab" : "сервис remont-lab"}</p> : null}
    </main>
  );
}
