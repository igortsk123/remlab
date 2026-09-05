"use client";

// Вход на /lab/mesh-audit — тот же секрет и кука, что у проверки ориентаций (/lab/mesh-review):
// закладка владельца `/api/lab/mesh-review/session?key=…` ставит куку на весь сайт.

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { loginWithSecret } from "@/lib/mesh-review/client";

export function MeshAuditLogin() {
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login() {
    setBusy(true);
    setError(null);
    const r = await loginWithSecret(secret);
    if (r === "ok") {
      window.location.reload();
      return;
    }
    setError(r === "wrong" ? "Неверный код" : "Вход недоступен");
    setBusy(false);
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-3 py-10">
      <h1 className="text-lg font-semibold text-primary">Приёмка мешей — вход</h1>
      <Input aria-label="Код доступа" type="password" value={secret} onChange={setSecret} placeholder="Код доступа" />
      <Button color="primary" onClick={() => void login()} isDisabled={!secret || busy} isLoading={busy}>
        Войти
      </Button>
      {error && <p className="text-sm text-error-primary">{error}</p>}
    </div>
  );
}
