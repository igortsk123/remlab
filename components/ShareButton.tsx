"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";

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
    <Button type="button" color="secondary" size="lg" onClick={copy}>
      {done ? "Ссылка скопирована ✓" : "Поделиться / сохранить ссылку"}
    </Button>
  );
}
