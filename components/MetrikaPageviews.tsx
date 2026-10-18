"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { METRIKA_COUNTER_ID, METRIKA_READY_EVENT, metrikaAllowed, metrikaSafeUrl } from "@/lib/metrika";

// Последний отправленный адрес: счётчик и страница стартуют в любом порядке, а хит на один адрес — один.
let lastHit: string | null = null;

// Next.js SPA-переходы не создают pageview сами — без явного ym('hit') URL-цели Метрики
// не считаются (грабли v0-health-card, analytics_caveats.md). Первый хит — тоже отсюда: счётчик
// стартует с `defer:true` (app/layout.tsx), иначе он сам отправил бы адрес с ключами покупателя.
function PageviewTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    const qs = searchParams.toString();
    const raw = pathname + (qs ? `?${qs}` : "");
    const url = metrikaSafeUrl(raw);
    const send = () => {
      // нет Метрики, страница менеджера/отчёта или английский режим без согласия — не шлём (b2b-02/03/04)
      if (!metrikaAllowed() || lastHit === url) return;
      // карта кликов шлёт location.href как есть — на адресе с ключом выключаем, на обычном включаем обратно
      window.ym?.(METRIKA_COUNTER_ID, "clickmap", url === raw);
      // откуда пришли — тоже без ключей (полная перезагрузка с /flat?s=…); дальше реферер — прошлый хит
      const opts = lastHit === null ? { referer: metrikaSafeUrl(document.referrer) } : {};
      window.ym?.(METRIKA_COUNTER_ID, "hit", url, opts);
      lastHit = url;
    };
    send();
    window.addEventListener(METRIKA_READY_EVENT, send);
    return () => window.removeEventListener(METRIKA_READY_EVENT, send);
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
