import Script from "next/script";
import { MeshAuditBatchBar } from "@/components/lab/MeshAuditBatchBar";
import { MeshAuditCard } from "@/components/lab/MeshAuditCard";
import { MeshAuditLogin } from "@/components/lab/MeshAuditLogin";
import { MeshAuditPager } from "@/components/lab/MeshAuditPager";
import { MeshAuditSeen } from "@/components/lab/MeshAuditSeen";
import { reviewerOk } from "@/lib/mesh-review/auth";
import { batchState, servedSkus } from "@/lib/mesh-audit/repo-batches";
import { listPage, toView } from "@/lib/mesh-audit/repo-items";
import { batchCount, batchOfPage, clampPage, PAGE_SIZE, pageCount, pagesOfBatch } from "@/lib/mesh-audit/rules";

export const metadata = {
  title: "Приёмка мешей",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

// Ручная приёмка мешей владельцем (план mesh-owner-audit): по 20 карточек на страницу, одна
// карточка на товар, у каждой вертящаяся 3D-модель (по клику) и кнопка «переделать».
// Доступ — кука владельца (та же, что у /lab/mesh-review); данные — read-model, который пушит DEV.
export default async function MeshAuditPage({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  if (!(await reviewerOk())) {
    return (
      <main className="mx-auto max-w-5xl px-4">
        <MeshAuditLogin />
      </main>
    );
  }
  const { page: rawPage } = await searchParams;
  const first = await listPage(1);
  const pages = pageCount(first.total);
  const page = clampPage(rawPage, pages);
  const { items, total, seen } = page === 1 ? first : await listPage(page);
  const batch = await batchState();
  const thisBatch = batchOfPage(page);
  // «есть 3D» — по списку моделей, реально лежащих на сервере (sku партии), а не по номеру
  // страницы: нумерация карточек плывёт при снятии ковров и цветовых вариантов, партия — нет
  const served = await servedSkus(batch);
  const views = items.map(toView);
  const modelUrl = (sku: string, modelPath: string): string | null => {
    const token = served.bySku.get(sku) ?? served.legacy.get(thisBatch);
    return token ? `/test/mesh-audit/releases/${token}/${modelPath}` : null;
  };

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-6">
      <Script src="/vendor/model-viewer.min.js" type="module" strategy="afterInteractive" />
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-primary">Приёмка мешей</h1>
        <span className="text-sm text-tertiary">
          просмотрено {seen} из {total} · страница {page} из {pages}
        </span>
      </header>
      <MeshAuditBatchBar thisBatch={thisBatch} totalBatches={batchCount(total)} pages={pagesOfBatch(thisBatch)} initial={batch} />
      <MeshAuditPager page={page} pages={pages} />
      {views.length === 0 ? (
        <p className="py-10 text-sm text-tertiary">Мешей в списке пока нет — конвейер ещё не отдал реестр.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {views.map((it, i) => (
            <MeshAuditCard key={it.id} item={it} rank={(page - 1) * PAGE_SIZE + i + 1} modelUrl={modelUrl(it.sku, it.modelPath)} />
          ))}
        </div>
      )}
      <MeshAuditPager page={page} pages={pages} />
      <MeshAuditSeen itemIds={views.map((v) => v.id)} />
    </main>
  );
}
