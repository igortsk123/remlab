import { startProject } from "@/app/actions";
import { SelectChips } from "@/components/SelectChips";
import { Progress } from "@/components/Progress";
import { ComingSoon } from "@/components/ComingSoon";

// Раздел закрыт заглушкой до запуска (launch-p1-vitrina); включение старого содержимого: NEXT_PUBLIC_SHOW_WIP=1.
const SHOW_WIP = process.env.NEXT_PUBLIC_SHOW_WIP === "1";

export const metadata = SHOW_WIP ? {} : {
  title: "Дизайн по фото: скоро",
  robots: { index: false, follow: true },
};

export default function StartPage() {
  if (!SHOW_WIP) {
    return (
      <ComingSoon
        icon="🖼️"
        iconSrc="/icons/dizayn.png"
        title="Дизайн по фото"
        lead="Загрузите фото комнаты и посмотрите, как она заиграет в новом стиле. Доводим качество результата до уровня, за который не стыдно."
      />
    );
  }
  return (
    <main className="container">
      <Progress step={1} />
      <h1>Что хотите сделать с комнатой?</h1>

      <form action={startProject} className="stack">
        <input type="hidden" name="goal" value="refresh" />

        <div className="stack">
          <label className="eyebrow">Комната</label>
          <SelectChips
            name="roomType"
            mode="single"
            initial={["living_room"]}
            options={[
              { value: "living_room", label: "Гостиная" },
              { value: "bedroom", label: "Спальня" },
              { value: "kids", label: "Детская — скоро", disabled: true },
              { value: "kitchen", label: "Кухня — скоро", disabled: true },
            ]}
          />
        </div>

        <div className="stack">
          <label className="eyebrow">Уровень обновления</label>
          <SelectChips
            name="interventionLevel"
            mode="single"
            initial={["refresh"]}
            options={[
              { value: "refresh", label: "Освежить без ремонта" },
              { value: "budget_update", label: "Недорого обновить" },
              { value: "light_cosmetic", label: "Лёгкий косметический" },
            ]}
          />
          <p className="muted" style={{ fontSize: 14 }}>
            Освежить — текстиль, свет, декор. Недорого обновить — покраска стены, часть мебели.
            Лёгкий косметический — стены, пол, свет (для точного расчёта нужны размеры).
          </p>
        </div>

        <button className="btn btn-block" type="submit">Продолжить</button>
      </form>
    </main>
  );
}
