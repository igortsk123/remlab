"use client";

// После передеплоя открытые вкладки «протухают»: серверные экшены форм меняют id → кнопки молча
// перестают работать. Этот сторож сравнивает версию, с которой загрузилась страница (`current`),
// с версией живого сервера (`/api/health`), и при расхождении показывает ненавязчивый баннер
// «обновите страницу» вместо тихой поломки. Проверка — периодически и при возврате на вкладку.

import { useEffect, useState } from "react";

export function VersionWatcher({ current }: { current: string }) {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (!current || stale) return;
    let alive = true;
    async function check() {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (!r.ok) return;
        const d = (await r.json()) as { version?: string };
        if (alive && d.version && d.version !== current) setStale(true);
      } catch {
        /* сеть недоступна — не мешаем пользователю */
      }
    }
    const id = setInterval(check, 60_000);
    const onFocus = () => check();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [current, stale]);

  if (!stale) return null;

  return (
    <div
      role="status"
      style={{
        position: "fixed", left: 12, right: 12, bottom: 12, zIndex: 9999,
        display: "flex", gap: 12, alignItems: "center", justifyContent: "center", flexWrap: "wrap",
        padding: "12px 16px", borderRadius: 12,
        background: "var(--text, #2b2b2b)", color: "var(--surface, #fff)",
        boxShadow: "0 6px 24px rgba(0,0,0,.18)", fontSize: 15,
      }}
    >
      <span>Вышло обновление сайта — обновите страницу, чтобы всё работало корректно.</span>
      <button
        onClick={() => location.reload()}
        style={{
          padding: "8px 16px", borderRadius: 8, border: "none", cursor: "pointer",
          background: "var(--accent, #7c9070)", color: "#fff", fontSize: 15, fontFamily: "inherit",
        }}
      >
        Обновить
      </button>
    </div>
  );
}
