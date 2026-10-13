import type { Metadata } from "next";
import { LegalPage } from "@/components/legal/LegalPage";

export const metadata: Metadata = { title: "Cookie и хранение в браузере — remont-lab" };

// Черновик для юриста (план b2b-04, ADR-0268); ?lang=en — английская версия.
export default async function Page({ searchParams }: { searchParams: Promise<{ lang?: string }> }) {
  const sp = await searchParams;
  return <LegalPage doc="cookies" lang={sp.lang === "en" ? "en" : "ru"} />;
}
