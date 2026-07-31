import Link from "next/link";
import type { StyleInfo } from "@/lib/styles/quiz";

// Карточка «Мой стиль» над вкладками лаборатории: результат игры «узнай свой вкус»
// или приглашение её пройти (с пометкой «скоро», пока раздел закрыт витриной).
export function MyStyleCard({ style, quizWip }: { style: StyleInfo | null; quizWip: boolean }) {
  if (!style) {
    return (
      <div className="card row" style={{ alignItems: "center", justifyContent: "space-between", marginTop: 20, gap: 12 }}>
        <p style={{ margin: 0 }}>
          🎨 Узнайте свой стиль интерьера — короткая игра-тест
          {quizWip && <span className="soon-badge">скоро</span>}
        </p>
        <Link className="btn btn-secondary" href="/styles">К игре</Link>
      </div>
    );
  }
  return (
    <div className="card row" style={{ alignItems: "center", marginTop: 20, gap: 14 }}>
      <span
        className="style-swatch"
        style={{ background: `linear-gradient(135deg, ${style.swatch[0]}, ${style.swatch[1]})` }}
        aria-hidden
      />
      <div style={{ flex: 1, minWidth: 160 }}>
        <strong>Ваш стиль: {style.name}</strong>
        <p className="muted" style={{ margin: "2px 0 0", fontSize: 14 }}>по итогам игры «узнай свой вкус»</p>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <Link className="btn btn-secondary" href="/styles">Пройти заново</Link>
        <Link className="btn" href="/start">Дизайн в этом стиле</Link>
      </div>
    </div>
  );
}
