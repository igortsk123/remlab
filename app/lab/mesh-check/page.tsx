import Script from "next/script";
import { MeshAuditLogin } from "@/components/lab/MeshAuditLogin";
import { MeshCheckBoard } from "@/components/lab/MeshCheckBoard";
import { MeshCheckReviewer } from "@/components/lab/MeshCheckReviewer";
import { reviewerOk } from "@/lib/mesh-review/auth";
import { batchState, servedSkus } from "@/lib/mesh-audit/repo-batches";
import { listSection, sectionCounts, type CheckFilter } from "@/lib/mesh-audit/repo-check";
import { toView } from "@/lib/mesh-audit/repo-items";
import { clampPage, pageCount } from "@/lib/mesh-audit/rules";
import { firstOpenSection, sectionByKey } from "@/lib/mesh-audit/sections";

export const metadata = {
  title: "Проверка мешей",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

const FILTERS: readonly CheckFilter[] = ["all", "todo", "bad"];

// Проверка мешей глазами (T-20261112-118, владелец TG 1361): фото товара и снимок модели рядом, «ок» / «брак», комментарий;
// разделы по типу товара. Вход — та же кука, что у /lab/mesh-audit; данные — тот же read-model, отметки — mesh_audit_marks/notes.
export default async function MeshCheckPage({ searchParams }: { searchParams: Promise<{ s?: string; f?: string; p?: string }> }) {
  if (!(await reviewerOk())) {
    return (
      <main className="mx-auto max-w-5xl px-4">
        <MeshAuditLogin />
      </main>
    );
  }
  const sp = await searchParams;
  const counts = await sectionCounts();
  const section = (sectionByKey(sp.s) && counts.some((c) => c.key === sp.s) ? sp.s : firstOpenSection(counts)) ?? "divan";
  const filter: CheckFilter = FILTERS.find((f) => f === sp.f) ?? "all";
  const head = await listSection(section, filter, 1);
  const pages = pageCount(head.total);
  const page = clampPage(sp.p, pages);
  const { items } = page === 1 ? head : await listSection(section, filter, page);
  const views = items.map(toView);
  // «покрутить 3D» — только где модель реально лежит на сервере (залитая партия), как на /lab/mesh-audit
  const served = await servedSkus(await batchState());
  const modelUrls = Object.fromEntries(
    views.map((v) => {
      const token = served.bySku.get(v.sku);
      return [v.id, token ? `/test/mesh-audit/releases/${token}/${v.modelPath}` : null];
    }),
  );

  return (
    <MeshCheckReviewer>
      <Script src="/vendor/model-viewer.min.js" type="module" strategy="afterInteractive" />
      <MeshCheckBoard
        key={`${section}:${filter}:${page}`}
        items={views}
        counts={counts}
        section={section}
        filter={filter}
        page={page}
        pages={pages}
        modelUrls={modelUrls}
      />
    </MeshCheckReviewer>
  );
}
