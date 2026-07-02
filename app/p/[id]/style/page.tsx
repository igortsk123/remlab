import { redirect } from "next/navigation";

// Экран выбора стиля переехал на объединённый экран /select (стиль выбирается вместе с разбором объектов).
// Оставляем редирект для старых ссылок/закладок.
export default async function StyleRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/p/${id}/select`);
}
