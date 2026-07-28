import Link from "next/link";

// Заглушка «в разработке» для разделов, закрытых до запуска (план launch-p1-vitrina).
// Старое содержимое страниц не удалено: включается флагом NEXT_PUBLIC_SHOW_WIP=1.
export function ComingSoon({ icon, title, lead }: { icon: string; title: string; lead: string }) {
  return (
    <main className="container">
      <span className="soon-pill">В разработке</span>
      <h1 style={{ marginTop: 14 }}>{icon} {title}</h1>
      <p className="muted" style={{ fontSize: 18 }}>{lead}</p>

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">Пока раздел готовится</p>
        <p style={{ margin: 0 }}>
          Главный инструмент уже работает: калькулятор посчитает обои, плитку, краску и ламинат,
          соберёт список покупок и сохранит его в Мою лабораторию.
        </p>
        <div className="row">
          <Link className="btn" href="/calc">🧮 Посчитать материалы</Link>
          <Link className="btn btn-secondary" href="/">На главную</Link>
        </div>
      </div>
    </main>
  );
}
