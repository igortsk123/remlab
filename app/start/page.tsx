import { startProject } from "@/app/actions";
import { SelectChips } from "@/components/SelectChips";
import { Progress } from "@/components/Progress";

export default function StartPage() {
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
