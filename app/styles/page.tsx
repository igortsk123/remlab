import { StyleQuiz } from "@/components/StyleQuiz";
import { STYLE_LIST } from "@/lib/styles/quiz";
import { ComingSoon } from "@/components/ComingSoon";

// Раздел закрыт заглушкой до запуска (launch-p1-vitrina); включение старого содержимого: NEXT_PUBLIC_SHOW_WIP=1.
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

export const metadata = {
  title: "Стили интерьера: узнай свой вкус",
  description:
    "Пройдите игру-карточки и узнайте свой стиль интерьера: скандинавский, лофт, джапанди, минимализм, классика, прованс.",
  ...(SHOW_WIP ? {} : { robots: { index: false, follow: true } }),
};

export default function StylesPage() {
  if (!SHOW_WIP) {
    return (
      <ComingSoon
        icon="🎨"
        title="Узнай свой стиль"
        lead="Короткая игра: отвечаете на пару вопросов о вкусах, получаете свой стиль интерьера и подборку идей для комнаты."
      />
    );
  }
  return (
    <main className="container">
      <p className="eyebrow">Стили</p>
      <h1>Узнай свой стиль</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Полистайте примеры интерьеров — что нравится, а что нет. В конце подскажем ваш стиль
        и покажем, как применить его к вашей комнате.
      </p>

      <div style={{ marginTop: 20 }}>
        <StyleQuiz />
      </div>

      <p className="eyebrow" style={{ marginTop: 36 }}>Про стили — скоро</p>
      <p className="muted" style={{ marginTop: 4, fontSize: 15 }}>
        Разбираем каждый стиль: что это, кому подойдёт, как повторить недорого. Статьи готовим — скоро здесь.
      </p>
      <div className="grid-cards" style={{ marginTop: 12 }}>
        {STYLE_LIST.map((s) => (
          <div key={s.id} className="card stack" style={{ gap: 8, opacity: 0.75 }}>
            <div
              style={{
                height: 10,
                borderRadius: 999,
                background: `linear-gradient(90deg, ${s.swatch[0]}, ${s.swatch[1]})`,
              }}
            />
            <strong>{s.name}</strong>
            <span className="muted" style={{ fontSize: 14 }}>Статья скоро</span>
          </div>
        ))}
      </div>
    </main>
  );
}
