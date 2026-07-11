"use client";

import { useState } from "react";

// Копирование постоянной ссылки на смету (шаринг + возврат к чек-листу).
export function ShareButton() {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      /* clipboard недоступен — no-op */
    }
  }
  return (
    <button type="button" className="btn btn-secondary" onClick={copy}>
      {done ? "Ссылка скопирована ✓" : "Поделиться / сохранить ссылку"}
    </button>
  );
}
