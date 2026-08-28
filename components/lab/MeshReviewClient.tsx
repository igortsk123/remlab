"use client";

// Проверка ориентации 3D-мешей (ADR-0131): владелец выбирает фронтальное положение кликом.
// Сеть — в lib/mesh-review/client.ts; решение append-only, идемпотентно по (task, choice).

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { loadTasks, loginWithSecret, sendDecision, type ReviewTask } from "@/lib/mesh-review/client";

const YAWS = ["0", "90", "180", "270"] as const;

const EXTRA: { choice: string; label: string }[] = [
  { choice: "symmetric", label: "Симметричен — фронт не нужен" },
  { choice: "bad_up", label: "Неверный верх" },
  { choice: "bad_mesh", label: "Меш непригоден" },
  { choice: "skip", label: "Пропустить" },
];

export function MeshReviewClient() {
  const [tasks, setTasks] = useState<ReviewTask[] | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const r = await loadTasks();
    if (r.kind === "login") {
      setNeedLogin(true);
      setTasks(null);
    } else if (r.kind === "error") {
      setError(r.message);
    } else {
      setNeedLogin(false);
      setTasks(r.tasks);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const login = useCallback(async () => {
    setError(null);
    const r = await loginWithSecret(secret);
    if (r === "ok") {
      setSecret("");
      void load();
    } else {
      setError(r === "wrong" ? "Неверный код" : "Вход недоступен");
    }
  }, [secret, load]);

  const decide = useCallback(async (task: ReviewTask, choice: string) => {
    setBusy(task.id);
    setError(null);
    const ok = await sendDecision(task, choice);
    if (ok) {
      setTasks((prev) => (prev ? prev.filter((t) => t.id !== task.id || choice === "skip") : prev));
    } else {
      setError("не сохранилось — повтори");
    }
    setBusy(null);
  }, []);

  if (needLogin) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-3 py-10">
        <h1 className="text-lg font-semibold text-primary">Проверка мешей — вход</h1>
        <Input aria-label="Код доступа" type="password" value={secret} onChange={setSecret} placeholder="Код доступа" />
        <Button color="primary" onClick={() => void login()} isDisabled={!secret}>
          Войти
        </Button>
        {error && <p className="text-sm text-error-primary">{error}</p>}
      </div>
    );
  }

  if (error && !tasks) {
    return (
      <div className="flex flex-col items-start gap-3 py-10">
        <p className="text-sm text-error-primary">Ошибка: {error}</p>
        <Button color="secondary" onClick={() => void load()}>
          Повторить
        </Button>
      </div>
    );
  }

  if (!tasks) return <p className="py-10 text-sm text-tertiary">Загрузка…</p>;

  if (tasks.length === 0) {
    return <p className="py-10 text-sm text-tertiary">Спорных мешей нет — всё решено автоматикой.</p>;
  }

  return (
    <div className="flex flex-col gap-8 py-6">
      <h1 className="text-lg font-semibold text-primary">Выбери фронтальное положение — осталось {tasks.length}</h1>
      {error && <p className="text-sm text-error-primary">{error}</p>}
      {tasks.map((t) => (
        <section key={t.id} className="flex flex-col gap-3 rounded-xl border border-secondary p-4">
          <header className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium text-primary">{t.payload.name ?? t.sku}</span>
            <span className="text-sm text-tertiary">
              {t.role ?? "?"} · {t.payload.source ?? "спорный"}
            </span>
          </header>
          <div className="flex flex-wrap items-start gap-4">
            {t.payload.photo && (
              <figure className="flex flex-col items-center gap-1">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={t.payload.photo} alt="фото товара" className="h-40 w-40 rounded-lg object-contain" />
                <figcaption className="text-xs text-tertiary">фото карточки</figcaption>
              </figure>
            )}
            {YAWS.map(
              (y) =>
                t.payload.renders?.[y] && (
                  <figure key={y} className="flex flex-col items-center gap-1">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={t.payload.renders[y]} alt={`ракурс ${y}°`} className="h-40 w-40 rounded-lg object-contain" />
                    <Button size="sm" color="secondary" isDisabled={busy === t.id} onClick={() => void decide(t, `front_${y}`)}>
                      Фронт — этот
                    </Button>
                  </figure>
                ),
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {EXTRA.map((e) => (
              <Button key={e.choice} size="sm" color="tertiary" isDisabled={busy === t.id} onClick={() => void decide(t, e.choice)}>
                {e.label}
              </Button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
