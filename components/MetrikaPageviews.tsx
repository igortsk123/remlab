"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { METRIKA_COUNTER_ID } from "@/lib/metrika";

// Next.js SPA-переходы не создают pageview сами — без явного ym('hit') URL-цели Метрики
// не считаются (грабли v0-health-card, analytics_caveats.md).
function PageviewTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.ym !== "function") return;
    const qs = searchParams.toString();
    window.ym(METRIKA_COUNTER_ID, "hit", pathname + (qs ? `?${qs}` : ""));
  }, [pathname, searchParams]);

  return null;
}

export function MetrikaPageviews() {
  return (
    <Suspense fallback={null}>
      <PageviewTracker />
    </Suspense>
  );
}
