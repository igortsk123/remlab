import Link from "next/link";
import { estimateRepo } from "@/modules/estimate/repository";
import { repo } from "@/modules/store/repository";
import { styleResultRepo } from "@/modules/style/repository";
import { readSessionId } from "@/lib/session";
import { splitEstimatesBySource } from "@/lib/estimate/lab-split";
import { STYLES } from "@/lib/styles/quiz";
import { track } from "@/lib/analytics";
import { EstimateRows } from "@/components/lab/EstimateRows";
import { LabTeaser } from "@/components/lab/LabTeaser";
import { MyStyleCard } from "@/components/lab/MyStyleCard";
import { plural } from "@/lib/format/plural";

export const metadata = {
  title: "Моя лаборатория: расчёты, сметы и дизайны",
  description: "Ваши сохранённые расчёты материалов, сметы ремонта и дизайны комнат в одном месте.",
};

// Разделы «Ремонт»/«Дизайны»/игра стилей пока закрыты витринами «Скоро» (launch-p1-vitrina).
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

type LabTab = "materials" | "remont" | "design";

const TABS: { key: LabTab; href: string; label: string }[] = [
  { key: "materials", href: "/lab", label: "Материалы" },
  { key: "remont", href: "/lab?tab=remont", label: "Ремонт" },
  { key: "design", href: "/lab?tab=design", label: "Дизайны" },
];

function resolveTab(raw: string | undefined): LabTab {
  return raw === "remont" || raw === "design" ? raw : "materials";
}

// Центр сохранений: вкладки Материалы / Ремонт / Дизайны + карточка «Мой стиль».
// Вкладки — обычные ссылки (?tab=...): работают прямые ссылки и «назад», клиентского JS не нужно.
export default async function LabPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const sp = await searchParams;
  const tab = resolveTab(sp.tab);
  const sid = await readSessionId();
  const estimates = sid ? await estimateRepo().listBySession(sid) : [];
  const rooms = sid ? await repo().listBySession(sid) : [];
  const styleRes = sid ? await styleResultRepo().get(sid) : null;
  const { materials, remont } = splitEstimatesBySource(estimates);
  // Интерес к вкладкам (в т.ч. закрытым «скоро») — только при явном ?tab, не блокируя рендер.
  if (sp.tab && sid) void track("lab_tab", sid, { tab });

  return (
    <main className="container">
      <p className="eyebrow">Моя лаборатория</p>
      <h1>Мои расчёты и проекты</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        Здесь собирается всё, что вы посчитали и придумали: расчёты материалов и ремонта, дизайны комнат.
      </p>

      <MyStyleCard style={styleRes ? STYLES[styleRes.style] : null} quizWip={!SHOW_WIP} />

      <nav className="lab-tabs" aria-label="Разделы лаборатории">
        {TABS.map((t) => (
          <Link key={t.key} href={t.href} className="lab-tab" data-active={tab === t.key} aria-current={tab === t.key ? "page" : undefined}>
            {t.label}
            {t.key === "materials" && materials.length > 0 && <span className="lab-badge">{materials.length}</span>}
            {t.key === "remont" && (remont.length > 0
              ? <span className="lab-badge">{remont.length}</span>
              : !SHOW_WIP && <span className="soon-badge">скоро</span>)}
            {t.key === "design" && (rooms.length > 0
              ? <span className="lab-badge">{rooms.length}</span>
              : !SHOW_WIP && <span className="soon-badge">скоро</span>)}
          </Link>
        ))}
      </nav>

      {tab === "materials" && (materials.length === 0 ? (
        <div className="card stack" style={{ marginTop: 20 }}>
          <p style={{ margin: 0 }}>Пока пусто. Посчитайте материалы — расчёт сохранится сюда.</p>
          <Link className="btn" href="/calc">Посчитать материалы</Link>
        </div>
      ) : (
        <div className="stack" style={{ marginTop: 20, gap: 12 }}>
          <EstimateRows estimates={materials} />
          <Link className="btn btn-secondary" href="/calc" style={{ alignSelf: "flex-start" }}>+ Новый расчёт</Link>
        </div>
      ))}

      {tab === "remont" && (remont.length === 0 ? (
        <LabTeaser
          icon="💰"
          title={SHOW_WIP ? "Сколько стоит ремонт" : "Скоро: сколько стоит ремонт"}
          lead="Укажете площадь, уровень отделки и регион — покажем вилку стоимости работ и материалов. Сохранённые расчёты будут появляться здесь."
          href="/calc/remont"
          cta={SHOW_WIP ? "Посчитать ремонт" : "Посмотреть раздел"}
        />
      ) : (
        <div className="stack" style={{ marginTop: 20, gap: 12 }}>
          <EstimateRows estimates={remont} />
          <Link className="btn btn-secondary" href="/calc/remont" style={{ alignSelf: "flex-start" }}>+ Новый расчёт</Link>
        </div>
      ))}

      {tab === "design" && (
        <LabTeaser
          icon="🎨"
          title={SHOW_WIP ? "Дизайн вашей комнаты по фото" : "Скоро: дизайн вашей комнаты по фото"}
          lead="Загрузите фото комнаты — ИИ покажет, как она будет выглядеть после ремонта в выбранном стиле. Готовые картинки будут храниться здесь."
          href="/start"
          cta={SHOW_WIP ? "Попробовать" : "Посмотреть раздел"}
        >
          {rooms.length > 0 && (
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              🛋️ Уже создано: <Link href="/rooms">{rooms.length} {plural(rooms.length, "комната", "комнаты", "комнат")}</Link>
            </p>
          )}
        </LabTeaser>
      )}
    </main>
  );
}
