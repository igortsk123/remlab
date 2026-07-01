import Link from "next/link";

export default function Home() {
  return (
    <main className="container">
      <p className="eyebrow">remont-lab</p>
      <h1>Обновите комнату с помощью AI</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Загрузите фото — получите визуальную идею обновления вашей комнаты, идеи, товары и
        материалы с примерным бюджетом и планом.
      </p>

      <div className="row" style={{ margin: "24px 0 8px" }}>
        <Link className="btn" href="/start">Обновить комнату</Link>
        <Link className="btn btn-secondary" href="/soon?f=cost">Рассчитать стоимость</Link>
      </div>

      <div className="card stack" style={{ marginTop: 28 }}>
        <p className="eyebrow">Как это работает</p>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Фото комнаты → короткий бриф</li>
          <li>Выбор стиля по карточкам</li>
          <li>AI-превью вашей комнаты + идеи и бюджет</li>
          <li>Полный план комнаты (товары, материалы, цены, PDF)</li>
        </ol>
        <p className="note">
          AI-превью — визуальная концепция вашей комнаты, а не рабочий проект. Перед покупкой
          проверяйте размеры.
        </p>
      </div>

      <p style={{ marginTop: 24 }}>
        <Link className="muted" href="/rooms">Мои комнаты →</Link>
      </p>
    </main>
  );
}
