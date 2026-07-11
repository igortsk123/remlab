import Link from "next/link";
import { notFound } from "next/navigation";
import { repo } from "@/modules/store/repository";
import { unlockPack } from "@/app/actions";
import { Progress } from "@/components/Progress";
import { PayButton } from "@/components/PayButton";

const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
const PRICE = 490;

export default async function PaywallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await repo().get(id);
  if (!project) notFound();

  if (project.paid) {
    return (
      <main className="container">
        <Progress step={5} />
        <h1>Полный план комнаты</h1>
        <p className="note">Демо-режим: оплата ещё не подключена, план открыт для примера.</p>
        <div className="stack" style={{ marginTop: 16 }}>
          {project.items.map((it, i) => (
            <div key={i} className="card">
              <p className="eyebrow" style={{ margin: 0 }}>{it.kind === "material" ? "материал" : "товар"} · {it.category}</p>
              <strong>{it.title}</strong>
              <p className="muted" style={{ margin: "4px 0 0" }}>{rub(it.priceRub)} · 3 альтернативы · ссылки (демо)</p>
            </div>
          ))}
        </div>
        <div className="card stack" style={{ marginTop: 16 }}>
          <strong>Также в пакете</strong>
          <p className="muted" style={{ margin: 0 }}>Чек-лист замеров · пошаговый план · PDF (демо) · обновление цен.</p>
        </div>
        <Link className="btn btn-block" href="/rooms" style={{ marginTop: 20 }}>Сохранить в «Мои комнаты»</Link>
      </main>
    );
  }

  return (
    <main className="container">
      <Progress step={5} />
      <h1>Откройте полный план комнаты</h1>
      <p className="muted">Вы увидели превью и часть идей. Полный план — платно.</p>

      <div className="card stack">
        <strong>Что внутри</strong>
        <ul className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Полный список товаров и материалов с ценами и ссылками</li>
          <li>3 альтернативы по ключевым позициям</li>
          <li>Подробный бюджет и чек-лист замеров</li>
          <li>Пошаговый план и PDF</li>
          <li>Сохранение и обновление цен в «Мои комнаты»</li>
        </ul>
      </div>

      <form action={unlockPack.bind(null, id)} style={{ marginTop: 20 }}>
        <PayButton label={`Оплатить ${rub(PRICE)} (демо)`} />
      </form>
      <p className="muted center" style={{ fontSize: 13, marginTop: 8 }}>
        Оплата — заглушка. Настоящая оплата (YooKassa) подключается отдельным шагом.
      </p>
    </main>
  );
}
