import type { Metadata } from "next";
import { ReportPage } from "@/components/partner/ReportPage";

export const metadata: Metadata = {
  title: "Отчёт по ссылкам покупателям",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// Отчёт застройщику (план b2b-03): без логина — ключ во #фрагменте адреса; Метрики на странице нет.
export default function Page() {
  return (
    <main className="container" style={{ paddingTop: 24, paddingBottom: 48 }}>
      <ReportPage />
    </main>
  );
}
