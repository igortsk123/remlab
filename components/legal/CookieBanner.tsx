"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";

// Баннер cookie (план b2b-04, ADR-0268). РФ-режим — уведомление «используем Метрику» (запоминается «Понятно»);
// английский (UK) — СОГЛАСИЕ: Метрика не запускается, пока человек не нажал «Accept» (`app/layout.tsx`,
// `window.__remlabMetrika`). На страницах менеджера и отчёта застройщику Метрики нет — баннера тоже.
export const COOKIE_KEY = "remlab-cookies";

export function isEnglishMode(search: string, stored: string | null): boolean {
  const q = new URLSearchParams(search).get("lang");
  return q ? q === "en" : stored === "en";
}

const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* приватный режим — спросим снова */ } };

export function CookieBanner() {
  const [mode, setMode] = useState<"hidden" | "ru" | "en">("hidden");
  // В 3D-КОНФИГУРАТОРЕ — КОМПАКТНО В УГЛУ (demo-05 п.8): плашка во всю ширину закрывала полосу выбора предметов внизу сцены.
  // Текст и выбор те же
  const [compact, setCompact] = useState(false);

  useEffect(() => {
    const p = location.pathname;
    if (p.startsWith("/manager") || p.startsWith("/partner")) return;
    const en = isEnglishMode(location.search, read("remlab-lang"));
    const v = read(COOKIE_KEY);
    if (en ? v !== "yes" && v !== "no" : v === null) setMode(en ? "en" : "ru");
    setCompact(p.startsWith("/flat"));
  }, []);

  if (mode === "hidden") return null;
  const done = (v: string) => {
    write(COOKIE_KEY, v);
    if (v === "yes") (window as unknown as { __remlabMetrika?: () => void }).__remlabMetrika?.();
    setMode("hidden");
  };
  return (
    <div role="region" aria-label={mode === "en" ? "Cookies" : "Cookie"}
      style={{ position: "fixed", left: 12, right: compact ? "auto" : 12, bottom: compact ? 8 : 12, zIndex: 50,
        maxWidth: compact ? 340 : 640, margin: compact ? 0 : "0 auto",
        background: "var(--color-bg-primary)", border: "1px solid var(--color-border-secondary)", borderRadius: 12,
        padding: compact ? "6px 10px" : "12px 16px", boxShadow: "0 6px 24px rgba(0,0,0,.12)", fontSize: compact ? 12 : undefined }}>
      {mode === "en" ? (
        <div className="stack" style={{ gap: 10 }}>
          <span style={{ fontSize: 14 }}>
            We would like to use analytics cookies (Yandex Metrica) to understand how the site is used. <a href="/cookies?lang=en">Details</a>
          </span>
          <div className="row" style={{ gap: 8 }}>
            <Button size="sm" onClick={() => done("yes")}>Accept</Button>
            <Button size="sm" color="secondary" onClick={() => done("no")}>Decline</Button>
          </div>
        </div>
      ) : (
        <div className="row" style={{ gap: 12, alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: compact ? 12 : 14 }}>
            Сайт использует cookie Яндекс.Метрики для статистики. <a href="/cookies">Подробнее</a>
          </span>
          <Button size="sm" color="secondary" onClick={() => done("ok")}>Понятно</Button>
        </div>
      )}
    </div>
  );
}
