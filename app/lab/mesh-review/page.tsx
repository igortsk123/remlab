import { MeshReviewClient } from "@/components/lab/MeshReviewClient";

export const metadata = {
  title: "Проверка 3D-мешей",
  robots: { index: false, follow: false },
};

// Единая страница человеческой проверки ориентаций (ADR-0131). Доступ — по коду
// (кука HttpOnly), задачи и решения ходят через /api/lab/mesh-review/*.
export default function MeshReviewPage() {
  return (
    <main className="mx-auto max-w-5xl px-4">
      <MeshReviewClient />
    </main>
  );
}
