import Link from "next/link";
import { notFound } from "next/navigation";
import { estimateRepo } from "@/modules/estimate/repository";
import { itemTotal, estimateTotal, type EstimateItem } from "@/contracts/estimate";
import { estimateLabel, estimateKind } from "@/lib/estimate/label";
import { CompanionChecklist } from "@/components/estimate/CompanionChecklist";
import { addLink, removeItem } from "@/app/estimate-actions";
import { ShareButton } from "@/components/ShareButton";
import { GoLink } from "@/components/GoLink";
import { Button } from "@/components/base/buttons/button";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
// Нативные поля в server-action форме (без клиентского JS), вид — токены UUI как у InputBase.
const inputCls =
  "w-full appearance-none rounded-lg bg-primary px-3 py-2 text-md text-primary shadow-xs ring-1 ring-primary outline-hidden transition duration-100 ease-linear ring-inset placeholder:text-fg-quaternary focus-visible:ring-2 focus-visible:ring-brand";

// Смета-чек-лист: постоянная ссылка (шаринг by design), живой документ.
export default async function EstimatePage({
  params, searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ saved?: string; err?: string }>;
}) {
  const { id } = await params;
  const { saved, err } = await searchParams;
  const est = await estimateRepo().get(id);
  if (!est) notFound();

  // Легаси-сопутка (раньше зашивалась позициями «1 шт») скрыта: теперь она — блок галочек
  // CompanionChecklist (ADR-0040). Данные не удаляем, старые расчёты очищаются отображением.
  const isCompanion = (i: EstimateItem) => i.note?.startsWith("сопутствующее") ?? false;
  const items = est.items.filter((i) => !isCompanion(i));
  const kind = estimateKind(est);

  const total = estimateTotal(est);
  const hasPrices = items.some((i) => i.unitPriceRub !== undefined);

  return (
    <main className="container">
      {/* Крошка заметной строкой, заголовок скромнее: сперва «где я», потом «что это» (ADR-0039/0040). */}
      <nav aria-label="Вы здесь" style={{ fontSize: 15 }}>
        <Link href="/lab" className="font-semibold text-brand-secondary">🧪 Моя лаборатория</Link>
        <span className="muted"> / расчёт</span>
      </nav>
      <h1 style={{ fontSize: 24, margin: "6px 0 0" }}>{estimateLabel(est)}</h1>
      {est.meta?.depthLabel ? <p className="muted" style={{ marginTop: -4 }}>{String(est.meta.depthLabel)}</p> : null}

      {saved ? (
        <p className="note">
          ✓ Сохранено в «Мою лабораторию». Эта страница — постоянная: можно вернуться к ней
          в любой момент или отправить кому-то.
        </p>
      ) : null}

      <div className="stack" style={{ marginTop: 16 }}>
        {items.map((it) => {
          const t = itemTotal(it);
          return (
            <div key={it.id} className="card row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <strong style={{ fontSize: 15 }}>{it.title}</strong>
                <p className="muted" style={{ margin: "2px 0 0", fontSize: 14 }}>
                  {it.qty} {it.unit}
                  {it.unitPriceRub !== undefined ? ` · ${rub(it.unitPriceRub)}/${it.unit}` : ""}
                  {t !== undefined ? ` · ${rub(t)}` : ""}
                </p>
                {it.note ? <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>{it.note}</p> : null}
                {it.url ? (
                  <GoLink href={`/go/${est.id}/${it.id}`} label={`Открыть ${it.domain ? `на ${it.domain}` : "ссылку"}`} />
                ) : null}
              </div>
              <form action={removeItem.bind(null, est.id, it.id)}>
                <Button type="submit" color="secondary" size="sm" className="rounded-full" aria-label="Убрать из списка">✕</Button>
              </form>
            </div>
          );
        })}
      </div>

      {kind ? <CompanionChecklist estimateId={est.id} kind={kind} /> : null}

      {hasPrices ? (
        <div className="card" style={{ marginTop: 16 }}>
          <p className="eyebrow" style={{ margin: 0 }}>Ориентировочно по позициям с ценой</p>
          <h2 style={{ margin: "6px 0 0" }}>{rub(total)}</h2>
          <p className="muted" style={{ fontSize: 13, margin: "4px 0 0" }}>
            Цены на дату добавления, у товаров по вашим ссылкам. Проверьте в магазине.
          </p>
        </div>
      ) : null}

      <div className="card stack" style={{ marginTop: 20 }}>
        <p className="eyebrow">Добавить свой товар по ссылке</p>
        {err === "url" ? <p className="note">Не похоже на ссылку — вставьте полный адрес (https://…).</p> : null}
        <form action={addLink.bind(null, est.id)} className="stack">
          <input name="url" placeholder="Ссылка на товар (Ozon, Леруа, ваш магазин…)" className={inputCls} aria-label="Ссылка на товар" />
          <div className="row" style={{ gap: 10 }}>
            <input name="title" placeholder="Название" className={inputCls} style={{ flex: 2, minWidth: 140 }} aria-label="Название" />
            <input name="qty" type="number" step="0.1" min="0" placeholder="Кол-во" className={inputCls} style={{ flex: 1, minWidth: 80 }} inputMode="decimal" aria-label="Количество" />
            <input name="price" type="number" step="1" min="0" placeholder="Цена, ₽" className={inputCls} style={{ flex: 1, minWidth: 90 }} inputMode="decimal" aria-label="Цена, ₽" />
          </div>
          <Button type="submit" color="secondary" size="md" className="self-start">Добавить в список</Button>
        </form>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Название и цену пока вписываете сами, так список полный и ничего не потеряется.
        </p>
      </div>

      <div className="row" style={{ marginTop: 20 }}>
        <ShareButton />
        <Button color="secondary" size="lg" href="/lab">← Все мои расчёты</Button>
      </div>

      <p style={{ marginTop: 24 }}>
        <Link className="muted" href="/calc">Ещё калькулятор</Link>
      </p>
    </main>
  );
}
