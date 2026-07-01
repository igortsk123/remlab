"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const STAGES = ["Проверяем фото…", "ИИ изучает комнату…", "Рисуем обновлённый интерьер…", "Собираем идеи…"];

export function GenerateOnMount({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [stage, setStage] = useState(0);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const timer = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 4000);
    (async () => {
      try {
        const res = await fetch(`/api/p/${projectId}/generate`, { method: "POST" });
        if (!res.ok) throw new Error("gen failed");
        if (alive) router.refresh();
      } catch {
        if (alive) setError(true);
      } finally {
        clearInterval(timer);
      }
    })();
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [projectId, router]);

  if (error) {
    return (
      <div className="stack center">
        <p className="note">Не получилось создать превью. Попробуйте ещё раз.</p>
        <button className="btn" onClick={() => location.reload()}>Повторить</button>
      </div>
    );
  }

  return (
    <div className="stack center" style={{ padding: "48px 0" }}>
      <div style={{ fontSize: 40 }}>🪄</div>
      <h2>Магия происходит…</h2>
      <p className="muted">{STAGES[stage]}</p>
    </div>
  );
}
