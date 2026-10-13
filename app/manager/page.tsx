import type { Metadata } from "next";
import { ManagerPage } from "@/components/manager/ManagerPage";

export const metadata: Metadata = {
  title: "Ссылки покупателям",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// Страница менеджера застройщика (план b2b-02): без логина — ключ во #фрагменте адреса.
export default function Page() {
  return (
    <main className="container" style={{ paddingTop: 24, paddingBottom: 48 }}>
      <ManagerPage />
    </main>
  );
}
