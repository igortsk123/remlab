import { notFound } from "next/navigation";
import { repo } from "@/modules/store/repository";
import { saveBrief } from "@/app/actions";
import { SelectChips } from "@/components/SelectChips";
import { Progress } from "@/components/Progress";

export default async function BriefPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await repo().get(id);
  if (!project) notFound();

  return (
    <main className="container">
      <Progress step={2} />
      <h1>Фото и короткий бриф</h1>
      <p className="muted">
        Снимите комнату из угла, чтобы попали стены, пол, окно и основная мебель. 1 фото достаточно.
      </p>

      <form action={saveBrief.bind(null, id)} className="stack" encType="multipart/form-data">
        <div className="card stack">
          <label className="eyebrow">Фото комнаты</label>
          <input type="file" name="photo" accept="image/*" />
        </div>

        <div className="stack">
          <label className="eyebrow">Город (для доставки и расчёта)</label>
          <input
            name="city"
            placeholder="Москва"
            style={{ padding: "12px 14px", borderRadius: 10, border: "1px solid var(--base)", background: "var(--surface)", color: "var(--text)", fontSize: 16 }}
          />
        </div>

        <div className="stack">
          <label className="eyebrow">Бюджет</label>
          <SelectChips
            name="budgetBand"
            mode="single"
            initial={["unknown"]}
            options={[
              { value: "u30", label: "до 30к" },
              { value: "30_70", label: "30–70к" },
              { value: "70_150", label: "70–150к" },
              { value: "150_300", label: "150–300к" },
              { value: "300p", label: ">300к" },
              { value: "unknown", label: "не знаю" },
            ]}
          />
        </div>

        <div className="stack">
          <label className="eyebrow">Что оставить</label>
          <SelectChips
            name="keep"
            options={[
              { value: "floor", label: "Пол" },
              { value: "walls", label: "Стены" },
              { value: "sofa_bed", label: "Диван/кровать" },
              { value: "wardrobe", label: "Шкаф" },
              { value: "curtains", label: "Шторы" },
              { value: "light", label: "Свет" },
              { value: "all_changeable", label: "Всё можно менять" },
            ]}
          />
        </div>

        <div className="stack">
          <label className="eyebrow">Ограничения</label>
          <SelectChips
            name="constraints"
            options={[
              { value: "kids", label: "Дети" },
              { value: "pets", label: "Животные" },
              { value: "for_rent", label: "Под сдачу" },
              { value: "no_drilling", label: "Нельзя сверлить" },
              { value: "no_painting", label: "Нельзя красить" },
              { value: "small", label: "Маленькая" },
              { value: "low_light", label: "Мало света" },
            ]}
          />
        </div>

        <button className="btn btn-block" type="submit">К выбору стиля</button>
      </form>
    </main>
  );
}
