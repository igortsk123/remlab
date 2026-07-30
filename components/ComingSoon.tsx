import Link from "next/link";

// Заглушка «в разработке» для разделов, закрытых до запуска (план launch-p1-vitrina).
// Старое содержимое страниц не удалено: включается флагом NEXT_PUBLIC_SHOW_WIP=1.
// iconSrc (картинка-иконка владельца) вытесняет emoji-icon, если задан.
export function ComingSoon({ icon, iconSrc, title, lead }: { icon: string; iconSrc?: string; title: string; lead: string }) {
  return (
    <main className="container">
      <span className="soon-pill">В разработке</span>
      <h1 style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
        {iconSrc ? (
          // Обычный <img>, НЕ next/image: standalone-прод без sharp (см. app/calc/page.tsx).
          // eslint-disable-next-line @next/next/no-img-element
          <img src={iconSrc} alt="" width={40} height={40} style={{ display: "block" }} />
        ) : (
          icon
        )}{" "}
        {title}
      </h1>
      <p className="muted" style={{ fontSize: 18 }}>{lead}</p>

      <div className="card stack" style={{ marginTop: 24 }}>
        <p className="eyebrow">Пока раздел готовится</p>
        <p style={{ margin: 0 }}>
          Главный инструмент уже работает: калькулятор посчитает обои, плитку, краску и ламинат,
          соберёт список покупок и сохранит его в Мою лабораторию.
        </p>
        <div className="row">
          <Link className="btn" href="/calc">Посчитать материалы</Link>
          <Link className="btn btn-secondary" href="/">На главную</Link>
        </div>
      </div>
    </main>
  );
}
