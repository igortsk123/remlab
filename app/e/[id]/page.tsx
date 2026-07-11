import Link from "next/link";
import { notFound } from "next/navigation";
import { estimateRepo } from "@/modules/estimate/repository";
import { itemTotal, estimateTotal } from "@/contracts/estimate";
import { addLink, removeItem, markSaved } from "@/app/estimate-actions";
import { ShareButton } from "@/components/ShareButton";
import { SaveButton } from "@/components/SaveButton";
import { GoLink } from "@/components/GoLink";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
const inputStyle = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, fontFamily: "inherit", width: "100%",
} as const;

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

  const total = estimateTotal(est);
  const hasPrices = est.items.some((i) => i.unitPriceRub !== undefined);

  return (
    <main className="container">
      <p className="eyebrow">Смета-список · сохраняется по этой ссылке</p>
      <h1>{est.title}</h1>
      {est.meta?.depthLabel ? <p className="muted" style={{ marginTop: -4 }}>{String(est.meta.depthLabel)}</p> : null}

      {saved ? <p className="note">Сохранено. Откройте эту ссылку в любой момент — список ждёт вас.</p> : null}

      <div className="stack" style={{ marginTop: 16 }}>
        {est.items.map((it) => {
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
                <button type="submit" className="chip" title="Убрать из списка">✕</button>
              </form>
            </div>
          );
        })}
      </div>

      {hasPrices ? (
        <div className="card" style={{ marginTop: 16 }}>
          <p className="eyebrow" style={{ margin: 0 }}>Ориентировочно по позициям с ценой</p>
          <h2 style={{ margin: "6px 0 0" }}>{rub(total)}</h2>
          <p className="muted" style={{ fontSize: 13, margin: "4px 0 0" }}>
            Цены — на дату добавления, у товаров по вашим ссылкам. Проверьте в магазине.
          </p>
        </div>
      ) : null}

      <div className="card stack" style={{ marginTop: 20 }}>
        <p className="eyebrow">Добавить свой товар по ссылке</p>
        {err === "url" ? <p className="note">Не похоже на ссылку — вставьте полный адрес (https://…).</p> : null}
        <form action={addLink.bind(null, est.id)} className="stack">
          <input name="url" placeholder="Ссылка на товар (Ozon, Леруа, ваш магазин…)" style={inputStyle} />
          <div className="row" style={{ gap: 10 }}>
            <input name="title" placeholder="Название" style={{ ...inputStyle, flex: 2, minWidth: 140 }} />
            <input name="qty" type="number" step="0.1" min="0" placeholder="Кол-во" style={{ ...inputStyle, flex: 1, minWidth: 80 }} inputMode="decimal" />
            <input name="price" type="number" step="1" min="0" placeholder="Цена, ₽" style={{ ...inputStyle, flex: 1, minWidth: 90 }} inputMode="decimal" />
          </div>
          <button type="submit" className="btn btn-secondary">Добавить в список</button>
        </form>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Название и цену пока вписываете сами — так список полный и ничего не потеряется.
        </p>
      </div>

      <div className="row" style={{ marginTop: 20 }}>
        <ShareButton />
        <form action={markSaved.bind(null, est.id)}>
          <SaveButton />
        </form>
      </div>

      <p style={{ marginTop: 24 }}>
        <Link className="muted" href="/estimates">Мои сметы</Link> · <Link className="muted" href="/calc">Ещё калькулятор</Link>
      </p>
    </main>
  );
}
