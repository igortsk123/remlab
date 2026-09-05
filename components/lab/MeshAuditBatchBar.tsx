"use client";

// Панель партии: есть ли 3D-модели этой партии на сервере, кнопка «загрузить партию» /
// «следующая партия», прогресс заливки (опрос раз в 8 с), предупреждение о смене партии.
// Партия = 200 товаров = 10 страниц ≈ 1,5 ГБ ≈ 12 минут заливки (замер 05.09).

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/base/buttons/button";
import { loadBatchState, requestBatch } from "@/lib/mesh-audit/client";
import type { BatchStateView } from "@/lib/mesh-audit/types";

interface Props {
  thisBatch: number;
  totalBatches: number;
  pages: [number, number];
  initial: BatchStateView;
  servedOnPage: number; // сколько карточек этой страницы реально с 3D (по sku партии)
  cardsOnPage: number;
}

function isServed(state: BatchStateView, batch: number): boolean {
  return state.active?.batch === batch || state.retiring?.batch === batch;
}

export function MeshAuditBatchBar({ thisBatch, totalBatches, pages, initial, servedOnPage, cardsOnPage }: Props) {
  const router = useRouter();
  const [state, setState] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const initialToken = initial.active?.token ?? null;

  useEffect(() => {
    if (!state.pending) return;
    const t = setInterval(async () => {
      const s = await loadBatchState();
      if (s) setState(s);
    }, 8000);
    return () => clearInterval(t);
  }, [state.pending]);

  async function ask(batch: number) {
    setBusy(true);
    setError(null);
    const r = await requestBatch(batch);
    if (r.kind === "error") setError(r.message);
    else setState((s) => ({ ...s, pending: r.batch }));
    setBusy(false);
  }

  const served = isServed(state, thisBatch);
  const changed = state.active && state.active.token !== initialToken;
  const pending = state.pending;
  // нумерация сдвинулась (сняты карточки) — часть страницы вне залитой партии
  const partial = served && cardsOnPage > 0 && servedOnPage < cardsOnPage;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-secondary p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium text-primary">
          Партия {thisBatch} из {totalBatches} · страницы {pages[0]}–{pages[1]}
        </span>
        {served && partial ? (
          <span className="text-warning-primary">
            3D на этой странице у {servedOnPage} из {cardsOnPage} — нумерация сдвинулась, партию можно перезалить
          </span>
        ) : served ? (
          <span className="text-success-primary">3D-модели на сервере — крутите по клику</span>
        ) : (
          <span className="text-tertiary">3D-моделей этой партии на сервере нет — только постеры</span>
        )}
      </div>
      {pending && (
        <p className="text-tertiary">
          Партия {pending.batch} готовится: {pending.status}
          {pending.filesTotal ? ` · ${pending.filesDone ?? 0} из ${pending.filesTotal} моделей` : ""}
          {pending.error ? ` · ${pending.error}` : ""} — можно подождать здесь, страница обновится сама.
        </p>
      )}
      {changed && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-warning-primary">Партия на сервере сменилась — обновите страницу.</span>
          <Button size="sm" color="secondary" onClick={() => router.refresh()}>
            Обновить
          </Button>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {!served && !pending && (
          <Button size="sm" color="primary" isDisabled={busy} isLoading={busy} onClick={() => void ask(thisBatch)}>
            Загрузить партию {thisBatch} (~12 минут)
          </Button>
        )}
        {served && partial && !pending && (
          <Button size="sm" color="primary" isDisabled={busy} isLoading={busy} onClick={() => void ask(thisBatch)}>
            Перезалить партию {thisBatch} (~6 минут)
          </Button>
        )}
        {served && !pending && thisBatch < totalBatches && (
          <Button size="sm" color="secondary" isDisabled={busy} isLoading={busy} onClick={() => void ask(thisBatch + 1)}>
            Следующая партия ({thisBatch + 1}) — текущая копия уйдёт с сервера
          </Button>
        )}
      </div>
      {error && <p className="text-error-primary">{error}</p>}
    </div>
  );
}
