import Link from "next/link";

export const metadata = {
  title: "remont-lab — ремонт своими руками: посчитать, собрать смету, не переплатить",
  description:
    "Помогаем сделать ремонт своими руками — хорошо и недорого: калькуляторы материалов, бюджет ремонта, дизайн по фото, свой стиль и советы. Смета сохраняется по ссылке.",
};

const SCENARIOS = [
  { href: "/calc", icon: "🧮", title: "Посчитать материалы", desc: "Обои, плитка, краска, ламинат — сколько нужно с запасом" },
  { href: "/calc/remont", icon: "💰", title: "Сколько стоит ремонт", desc: "Бюджет комнаты по площади: работы и материалы отдельно" },
  { href: "/start", icon: "🖼️", title: "Дизайн по фото", desc: "Загрузите фото — ИИ покажет комнату в новом стиле" },
  { href: "/styles", icon: "🎨", title: "Узнай свой стиль", desc: "Полистайте интерьеры — подскажем, что вам ближе" },
  { href: "/sovety", icon: "🛠️", title: "Советы по ремонту", desc: "Как клеить, грунтовать, штукатурить — своими руками" },
  { href: "/lab", icon: "🧪", title: "Моя лаборатория", desc: "Сохранённые сметы и дизайны — всё в одном месте" },
];

export default function Home() {
  return (
    <main className="container">
      <p className="eyebrow">Ремонт своими руками</p>
      <h1>Сделайте ремонт хорошо и недорого — сами</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        remont-lab — помощник по ремонту: посчитать материалы и бюджет, собрать смету-список,
        подобрать стиль и не переплатить. Смета сохраняется по ссылке — чтобы в магазине ничего не забыть.
      </p>

      <div className="row" style={{ margin: "24px 0 8px", gap: 12 }}>
        <Link className="btn" href="/calc" style={{ flex: "1 1 220px" }}>🧮 Посчитать материалы</Link>
        <Link className="btn btn-secondary" href="/calc/remont" style={{ flex: "1 1 220px" }}>💰 Сколько стоит ремонт</Link>
      </div>

      <p className="eyebrow" style={{ marginTop: 28 }}>Что внутри</p>
      <div className="grid-cards" style={{ marginTop: 12 }}>
        {SCENARIOS.map((s) => (
          <Link key={s.href} href={s.href} className="card stack" style={{ textDecoration: "none", gap: 6 }}>
            <span style={{ fontSize: 28 }}>{s.icon}</span>
            <strong>{s.title}</strong>
            <span className="muted" style={{ fontSize: 14 }}>{s.desc}</span>
          </Link>
        ))}
      </div>

      <div className="card stack" style={{ marginTop: 28 }}>
        <p className="eyebrow">Как это работает</p>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Посчитали количество материалов или прикинули бюджет</li>
          <li>Собрали смету-список — с сопутствующими, чтобы не забыть</li>
          <li>Добавили свои ссылки на товары, сохранили по ссылке</li>
          <li>Купили по списку — ничего не потерялось и не переплатили</li>
        </ol>
      </div>

      <p className="muted center" style={{ marginTop: 28, fontSize: 15 }}>
        Ремонт — это не страшно. Считаем, показываем и подсказываем — а делаете вы сами.
      </p>
    </main>
  );
}
