"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { LoadingIndicator } from "@/components/application/loading-indicator/loading-indicator";
import { SendRow } from "@/components/manager/SendRow";
import type { ManagerData } from "@/components/manager/types";

// Страница менеджера застройщика (план b2b-02). Ключ — во #фрагменте адреса: он не уходит на сервер
// адресом, не попадает в журнал и в Метрику (она на /manager выключена, `app/layout.tsx`).
const keyFromHash = () => (typeof window === "undefined" ? "" : window.location.hash.replace(/^#/, ""));

export function ManagerPage() {
  const [data, setData] = useState<ManagerData | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "denied" | "error">("loading");
  const [busy, setBusy] = useState(false);

  const call = useCallback(async (path: string, body?: object) => {
    const res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "x-manager-key": keyFromHash(), ...(body ? { "content-type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    return { status: res.status, json: await res.json().catch(() => null) };
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await call("/api/manager");
      if (r.status === 403) return setState("denied");
      if (r.status !== 200 || !r.json?.ok) return setState("error");
      setData(r.json as ManagerData);
      setState("ready");
    } catch {
      setState("error");
    }
  }, [call]);

  useEffect(() => { void load(); }, [load]);

  const act = async (path: string, body: object) => {
    setBusy(true);
    try { await call(path, body); await load(); } finally { setBusy(false); }
  };

  if (state === "loading") return <div className="stack center" style={{ padding: 48 }}><LoadingIndicator label="Загружаем ваши ссылки" /></div>;
  if (state === "denied") return <p className="note">Ссылка на страницу менеджера неверная или устарела. Попросите новую у remont-lab.</p>;
  if (state === "error" || !data) {
    return <div className="stack"><p className="note">Не получилось загрузить. Проверьте интернет.</p><Button onClick={() => void load()}>Повторить</Button></div>;
  }

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="stack" style={{ gap: 4 }}>
        <h1 style={{ margin: 0 }}>{data.manager.name}: ссылки покупателям</h1>
        <p className="muted" style={{ margin: 0 }}>
          {data.manager.telegramConnected ? "Сигналы приходят вам в Telegram." : "Telegram не подключён — сигналы видны только здесь."}
        </p>
      </div>
      {data.apartments.map((a) => (
        <Button key={a.id} size="lg" isDisabled={busy} onClick={() => void act("/api/manager/sends", { apartmentId: a.id })}>
          Новая ссылка: {a.title}
        </Button>
      ))}
      {data.sends.length === 0
        ? <p className="muted">Ссылок пока нет. После показа нажмите «Новая ссылка» и перешлите её покупателю.</p>
        : data.sends.map((s) => <SendRow key={s.id} row={s} onStatus={(id, body) => void act(`/api/manager/sends/${id}`, body)} />)}
    </div>
  );
}
