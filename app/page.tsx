import Link from "next/link";

export default function Home() {
  return (
    <main className="container">
      <p className="eyebrow">remont-lab</p>
      <h1>Посчитайте ремонт и соберите смету — за минуту</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Сколько нужно материалов, сколько всё стоит и что купить. Собираем список-смету,
        которая сохраняется по ссылке — чтобы в магазине ничего не забыть.
      </p>

      <div className="stack" style={{ margin: "24px 0 8px", gap: 12 }}>
        <Link className="card row" href="/calc" style={{ textDecoration: "none", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ fontSize: 17 }}>🧮 Посчитать материалы</strong>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 15 }}>Обои, плитка, краска, ламинат — сколько нужно с запасом</p>
          </div>
          <span className="muted">→</span>
        </Link>
        <Link className="card row" href="/calc/remont" style={{ textDecoration: "none", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ fontSize: 17 }}>💰 Сколько стоит ремонт</strong>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 15 }}>Бюджет комнаты по площади: работы и материалы отдельно</p>
          </div>
          <span className="muted">→</span>
        </Link>
      </div>

      <div className="card stack" style={{ marginTop: 20 }}>
        <p className="eyebrow">Как это работает</p>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Посчитали количество или прикинули бюджет</li>
          <li>Собрали смету-список — с сопутствующими, чтобы не забыть</li>
          <li>Добавили свои ссылки на товары, сохранили по ссылке</li>
          <li>Купили по списку — ничего не потерялось</li>
        </ol>
      </div>

      <p className="muted" style={{ marginTop: 20, fontSize: 15 }}>
        Хотите увидеть, как комната будет выглядеть? <Link href="/start">Дизайн по фото с ИИ →</Link>
      </p>
      <p style={{ marginTop: 8 }}>
        <Link className="muted" href="/estimates">Мои сметы →</Link>
      </p>
    </main>
  );
}
