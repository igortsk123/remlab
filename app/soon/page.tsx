import Link from "next/link";

export default function SoonPage() {
  return (
    <main className="container">
      <p className="eyebrow">Скоро</p>
      <h1>Расчёт стоимости ремонта</h1>
      <p className="muted">
        Точный расчёт бюджета (работы, материалы, коэффициенты города) считает отдельный движок —
        мы его готовим. Оставьте email, сообщим, когда откроем.
      </p>

      <form className="stack" style={{ marginTop: 16, maxWidth: 420 }}>
        <input
          type="email"
          placeholder="you@example.com"
          style={{ padding: "12px 14px", borderRadius: 10, border: "1px solid var(--base)", background: "var(--surface)", color: "var(--text)", fontSize: 16 }}
        />
        <button className="btn" type="button">Сообщить, когда откроется</button>
        <p className="muted" style={{ fontSize: 13 }}>Демо: форма пока не отправляется.</p>
      </form>

      <p style={{ marginTop: 24 }}>
        <Link className="btn btn-secondary" href="/start">Пока обновить комнату визуально</Link>
      </p>
    </main>
  );
}
