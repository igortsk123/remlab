"use client";

import { useEffect } from "react";

// «Открыл квартиру в 3D» (план b2b-03): по ссылке менеджера — событие его отправки (персональная воронка),
// без неё — анонимный счётчик дня. Один раз на открытие страницы; сбой сети не мешает 3D.
export function OpenBeacon({ apartmentId, sendId, lang }: { apartmentId: string; sendId: string | null; lang: "ru" | "en" }) {
  useEffect(() => {
    const [url, body] = sendId
      ? [`/api/sends/${sendId}/event`, { kind: "flat3d_open" }]
      : ["/api/events", { apartmentId, kind: "flat3d_open", lang }];
    fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), keepalive: true }).catch(() => undefined);
  }, [apartmentId, sendId, lang]);
  return null;
}
