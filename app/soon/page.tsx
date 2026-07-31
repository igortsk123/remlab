import { Button } from "@/components/base/buttons/button";

const inputCls =
  "w-full appearance-none rounded-lg bg-primary px-3.5 py-2.5 text-md text-primary shadow-xs ring-1 ring-primary outline-hidden transition duration-100 ease-linear ring-inset placeholder:text-fg-quaternary focus-visible:ring-2 focus-visible:ring-brand";

export default function SoonPage() {
  return (
    <main className="container">
      <p className="eyebrow">Скоро</p>
      <h1>Расчёт стоимости ремонта</h1>
      <p className="muted">
        Точный расчёт бюджета (работы, материалы, коэффициенты города) считает отдельный движок,
        мы его готовим. Оставьте email, сообщим, когда откроем.
      </p>

      <form className="stack" style={{ marginTop: 16, maxWidth: 420 }}>
        <input type="email" placeholder="you@example.com" className={inputCls} aria-label="E-mail" />
        <Button size="lg" type="button">Сообщить, когда откроется</Button>
        <p className="muted" style={{ fontSize: 13 }}>Демо: форма пока не отправляется.</p>
      </form>

      <p style={{ marginTop: 24 }}>
        <Button color="secondary" size="lg" href="/start">Пока обновить комнату визуально</Button>
      </p>
    </main>
  );
}
