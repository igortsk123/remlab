import Link from "next/link";

export const metadata = {
  title: "Советы по ремонту своими руками — поклейка, грунтовка, штукатурка",
  description:
    "Практические советы, как сделать ремонт своими руками: подготовка стен, грунтовка, штукатурка, поклейка обоев, покраска, укладка пола и плитки.",
};

const TIPS = [
  { icon: "🧻", title: "Поклейка обоев", desc: "Как клеить ровно и без пузырей" },
  { icon: "🪣", title: "Грунтовка стен", desc: "Зачем и как грунтовать перед отделкой" },
  { icon: "🧱", title: "Штукатурка", desc: "Выравнивание стен своими руками" },
  { icon: "🎨", title: "Покраска", desc: "Ровный цвет без разводов" },
  { icon: "🪵", title: "Укладка пола", desc: "Ламинат и подложка без ошибок" },
  { icon: "🚿", title: "Плитка в ванной", desc: "Раскладка и затирка швов" },
];

export default function SovetyPage() {
  return (
    <main className="container">
      <p className="eyebrow">Советы</p>
      <h1>Ремонт своими руками</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Пошаговые советы по отделке: как подготовить стены, поклеить обои, положить плитку
        и не переделывать. Раздел наполняется — скоро здесь появятся статьи.
      </p>

      <div className="grid-cards" style={{ marginTop: 20 }}>
        {TIPS.map((t) => (
          <div key={t.title} className="card stack" style={{ gap: 6, opacity: 0.8 }}>
            <span style={{ fontSize: 26 }}>{t.icon}</span>
            <strong>{t.title}</strong>
            <span className="muted" style={{ fontSize: 14 }}>{t.desc}</span>
            <span className="muted" style={{ fontSize: 13 }}>Скоро →</span>
          </div>
        ))}
      </div>

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">Пока раздел готовится</p>
        <p style={{ margin: 0 }}>А смету на материалы можно собрать уже сейчас — посчитаем количество и стоимость.</p>
        <div className="row">
          <Link className="btn" href="/calc">Посчитать материалы</Link>
          <Link className="btn btn-secondary" href="/calc/remont">Стоимость ремонта</Link>
        </div>
      </div>
    </main>
  );
}
