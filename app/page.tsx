import Link from "next/link";
import { LabBadge } from "@/components/LabBadge";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";

// Пилюля «Скоро» на плитках/кнопках главной.
const Soon = () => (
  <span className="ml-2 inline-block align-middle"><Badge type="pill-color" color="slate" size="sm">Скоро</Badge></span>
);

export const metadata = {
  title: "remont-lab: посчитать материалы для ремонта и собрать смету",
  description:
    "Помощник по ремонту своими руками. Калькуляторы обоев, плитки, краски и ламината: посчитаем количество с запасом, соберём список покупок и сохраним смету по ссылке.",
};

// soon: сервис закрыт заглушкой до запуска (launch-p1-vitrina) — плитка ведёт на страницу «в разработке».
// iconSrc — картинка-иконка владельца (public/icons/, единый стиль); без неё плитка живёт на emoji.
const SCENARIOS = [
  { href: "/calc", icon: "🧮", iconSrc: "/icons/materialy.png", title: "Посчитать материалы", desc: "Обои, плитка, краска, ламинат: сколько нужно с запасом", soon: false },
  { href: "/calc/remont", icon: "💰", title: "Сколько стоит ремонт", desc: "Бюджет комнаты по площади: работы и материалы отдельно", soon: true },
  { href: "/start", icon: "🖼️", iconSrc: "/icons/dizayn.png", title: "Дизайн по фото", desc: "Загрузите фото, и ИИ покажет комнату в новом стиле", soon: true },
  { href: "/styles", icon: "🎨", title: "Узнай свой стиль", desc: "Полистайте интерьеры, подскажем, что вам ближе", soon: true },
  { href: "/sovety", icon: "🛠️", title: "Советы по ремонту", desc: "Как клеить, грунтовать и штукатурить своими руками", soon: true },
  { href: "/lab", icon: "🧪", title: "Моя лаборатория", desc: "Сохранённые расчёты и дизайны всегда под рукой", soon: false },
];

export default function Home() {
  return (
    <main className="container">
      <p className="eyebrow">Ремонт своими руками</p>
      <h1>Сделайте ремонт хорошо и недорого. Сами.</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        remont-lab: помощник по ремонту. Посчитайте материалы и бюджет, соберите смету — список
        покупок, подберите стиль и не переплатите. Расчёт сохраняется по ссылке, чтобы в магазине
        ничего не забыть.
      </p>

      <div className="row" style={{ margin: "24px 0 8px", gap: 12 }}>
        <Button size="lg" href="/calc" className="flex-[1_1_220px]">Посчитать материалы</Button>
        <Button color="secondary" size="lg" href="/calc/remont" className="flex-[1_1_220px]">
          Сколько стоит ремонт<Soon />
        </Button>
      </div>

      <p className="eyebrow" style={{ marginTop: 28 }}>Что внутри</p>
      <div className="grid-cards" style={{ marginTop: 12 }}>
        {SCENARIOS.map((s) => (
          <Link key={s.href} href={s.href} className="card stack" style={{ textDecoration: "none", gap: 6 }}>
            {"iconSrc" in s && s.iconSrc ? (
              // Обычный <img>, НЕ next/image: standalone-прод без sharp (см. app/calc/page.tsx).
              // eslint-disable-next-line @next/next/no-img-element
              <img src={s.iconSrc} alt="" width={44} height={44} style={{ display: "block" }} />
            ) : (
              <span style={{ fontSize: 28 }}>{s.icon}</span>
            )}
            <strong>
              {s.title}
              {s.soon && <Soon />}
              {s.href === "/lab" && <LabBadge />}
            </strong>
            <span className="muted" style={{ fontSize: 14 }}>{s.desc}</span>
          </Link>
        ))}
      </div>

      <div className="card stack" style={{ marginTop: 28 }}>
        <p className="eyebrow">Как это работает</p>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Введите размеры комнаты в калькуляторе</li>
          <li>Получите количество материалов с запасом и цены</li>
          <li>Сохраните расчёт в Мою лабораторию и добавьте ссылки на товары</li>
          <li>Покупайте по списку: ничего не забудете и не переплатите</li>
        </ol>
      </div>

      <p className="muted center" style={{ marginTop: 28, fontSize: 15 }}>
        Ремонт перестаёт пугать, когда всё посчитано. Считаем и подсказываем, а делаете вы сами.
      </p>
    </main>
  );
}
