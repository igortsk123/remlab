import { CutoutCheckBoard } from "@/components/lab/CutoutCheckBoard";
import { MeshAuditLogin } from "@/components/lab/MeshAuditLogin";
import { MeshCheckReviewer } from "@/components/lab/MeshCheckReviewer";
import { currentRun, listPage, roleCounts, toView } from "@/lib/cutout-check/repo-items";
import { clampPage, pageCount, parseFilter } from "@/lib/cutout-check/rules";
import { reviewerOk } from "@/lib/mesh-review/auth";

export const metadata = {
  title: "Проверка вырезок / Cutout check",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

// Проверка вырезок глазами (T-20261119-104, владелец TG 2098/2102): по каждому товару /demo — фото магазина и вырезка (шахматка и тёмный фон),
// «Ок» / «Не ок» и «что не так». Вход — та же кука, что у /lab/mesh-audit; отметки — cutout_check_items/marks, список — /api/lab/cutout-check/export.
export default async function CutoutCheckPage({ searchParams }: { searchParams: Promise<{ r?: string; f?: string; p?: string }> }) {
  if (!(await reviewerOk())) {
    return (
      <main className="mx-auto max-w-5xl px-4">
        <MeshAuditLogin title="Проверка вырезок — вход / Cutout check — sign in" />
      </main>
    );
  }
  const run = await currentRun();
  if (!run) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-10 text-center text-sm text-tertiary">
        Вырезок для проверки пока нет. / No cutouts to check yet.
      </main>
    );
  }
  const sp = await searchParams;
  const { roles, all } = await roleCounts(run);
  const role = roles.some((c) => c.role === sp.r) ? (sp.r ?? null) : null;
  const filter = parseFilter(sp.f);
  const head = await listPage(run, role, filter, 1);
  const pages = pageCount(head.total);
  const page = clampPage(sp.p, pages);
  const { items } = page === 1 ? head : await listPage(run, role, filter, page);

  return (
    <MeshCheckReviewer>
      <CutoutCheckBoard key={`${role}:${filter}:${page}`} run={run} items={items.map(toView)} roles={roles} all={all} role={role} filter={filter} page={page} pages={pages} />
    </MeshCheckReviewer>
  );
}
