import { notFound } from "next/navigation";
import { repo } from "@/modules/store/repository";
import { saveSelection } from "@/app/actions";
import { Progress } from "@/components/Progress";
import { SelectRoom } from "@/components/SelectRoom";

// Экран «Что меняем на фото?» — разбор объектов (analyze на монтировании) + выбор стиля + пожелание.
export default async function SelectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await repo().get(id);
  if (!project) notFound();

  const thumb = project.photos[0]?.dataUrl ?? null;
  const initialObjects = project.analysis?.objects ?? null;
  const initialStyles = project.styleProfile?.selectedStyleIds ?? [];

  return (
    <main className="container">
      <Progress step={3} />
      <h1>Что меняем на фото?</h1>
      <p className="muted">
        Мы разобрали вашу комнату. По каждому предмету выберите: оставить, поменять или убрать.
        Ниже одним полем опишите, каким хотите видеть результат.
      </p>

      <SelectRoom
        id={id}
        thumb={thumb}
        initialObjects={initialObjects}
        initialStyles={initialStyles}
        action={saveSelection.bind(null, id)}
      />
    </main>
  );
}
