"use client";

// Карточка меша: постер → по клику вертящаяся 3D-модель (GLB грузится ТОЛЬКО после клика:
// 20 моделей по 7,6 МБ разом — 150 МБ на страницу); одна кнопка «переделать»; бейдж состояния.
// Сеть — lib/mesh-audit/client.ts; правила — lib/mesh-audit/rules.ts.

import { useState } from "react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { cancelDecision, sendDecision } from "@/lib/mesh-audit/client";
import { MAX_MANUAL_REDO, PENDING_STATUSES, type Verdict } from "@/lib/mesh-audit/rules";
import type { AuditItemView } from "@/lib/mesh-audit/types";

interface Props {
  item: AuditItemView;
  rank: number;
  modelUrl: string | null; // null — модели этой партии нет на сервере
}

function stateBadge(item: AuditItemView) {
  const n = `${item.manualAttempts}/${MAX_MANUAL_REDO}`;
  if (item.status === "replace_needed") return { color: "error" as const, text: "нужна замена товара/фото" };
  if (item.status === "redo_requested") return { color: "warning" as const, text: `на переделке ${n} · принято, ждёт сборки очереди` };
  if (item.status === "redo_queued") return { color: "warning" as const, text: `на переделке ${n} · в очереди` };
  if (item.status === "redo_blocked") return { color: "error" as const, text: `переделка не удалась: ${item.reworkError ?? "см. конвейер"}` };
  if (item.redoneAt) return { color: "success" as const, text: `сделан заново · переделок ${n}` };
  if (item.manualAttempts > 0) return { color: "gray" as const, text: `переделок ${n}` };
  return null;
}

export function MeshAuditCard({ item: initial, rank, modelUrl }: Props) {
  const [item, setItem] = useState(initial);
  const [show3d, setShow3d] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pending = PENDING_STATUSES.has(item.status);
  const canRedo = !pending && item.status !== "replace_needed" && item.manualAttempts < MAX_MANUAL_REDO;
  const canReplace = !pending && item.status !== "replace_needed" && item.manualAttempts >= MAX_MANUAL_REDO;
  // случайный клик отменяется, пока переделка не ушла в снимок очереди
  const canCancel = item.status === "redo_requested" || item.status === "replace_needed";
  const badge = stateBadge(item);
  const date = item.generatedAt ? new Date(item.generatedAt).toLocaleDateString("ru-RU") : "—";

  async function act(run: () => ReturnType<typeof sendDecision>) {
    setBusy(true);
    setError(null);
    const r = await run();
    if (r.kind === "ok") setItem(r.item);
    else if (r.kind === "login") setError("сессия истекла — обновите страницу");
    else setError(r.message);
    setBusy(false);
  }
  const decide = (verdict: Verdict) => act(() => sendDecision(item, verdict));
  const undo = () => act(() => cancelDecision(item));

  return (
    <section className="flex flex-col gap-2 rounded-xl border border-secondary p-3" data-sku={item.sku}>
      <div className="relative aspect-square w-full overflow-hidden rounded-lg bg-secondary">
        {show3d && modelUrl ? (
          <model-viewer
            src={modelUrl}
            poster={item.posterUrl ?? undefined}
            alt={item.name ?? item.sku}
            camera-controls=""
            auto-rotate=""
            shadow-intensity="1"
            style={{ width: "100%", height: "100%" }}
          />
        ) : (
          <button
            type="button"
            className="relative h-full w-full cursor-pointer"
            onClick={() => modelUrl && setShow3d(true)}
            aria-label={modelUrl ? "Покрутить 3D-модель" : "3D-модель этой партии не загружена"}
          >
            {item.posterUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={item.posterUrl} alt="" className="h-full w-full object-contain" loading="lazy" />
            ) : (
              <span className="flex h-full items-center justify-center text-sm text-tertiary">постера ещё нет</span>
            )}
            <span className="absolute bottom-2 left-2 rounded-md bg-primary px-2 py-1 text-xs text-secondary shadow-xs ring-1 ring-primary ring-inset">
              {modelUrl ? "▶ покрутить 3D" : "3D — в другой партии"}
            </span>
          </button>
        )}
        {item.imageUrl && (
          <a href={item.imageUrl} target="_blank" rel="noreferrer" className="absolute top-2 right-2" title="Открыть фото товара в полный размер">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={item.imageUrl} alt="фото товара" className="h-20 w-20 rounded-md bg-primary object-contain ring-1 ring-primary" loading="lazy" />
          </a>
        )}
      </div>
      <div className="flex flex-col gap-0.5 text-xs text-tertiary">
        <span className="text-sm font-medium text-primary">
          #{rank} · {item.name || item.sku}
        </span>
        <span>
          {item.role ?? "?"} · {item.sku} · {date} · попытка {item.attempt ?? "?"} (seed {item.seed ?? "?"})
        </span>
        {item.variantsNote && <span className="text-secondary">{item.variantsNote}</span>}
        {item.photoStale && <span className="text-warning-primary">меш от старого фото — перегенерируется сам</span>}
      </div>
      {badge && (
        <span>
          <Badge type="pill-color" color={badge.color} size="sm">
            {badge.text}
          </Badge>
        </span>
      )}
      <div className="flex flex-wrap gap-2">
        {canRedo && (
          <Button size="sm" color="primary" isDisabled={busy} isLoading={busy} onClick={() => void decide("redo")}>
            Переделать
          </Button>
        )}
        {canReplace && (
          <Button size="sm" color="secondary" isDisabled={busy} isLoading={busy} onClick={() => void decide("replace_needed")}>
            Нужна замена товара/фото
          </Button>
        )}
        {canCancel && (
          <Button size="sm" color="tertiary" isDisabled={busy} isLoading={busy} onClick={() => void undo()}>
            Отменить (нажал случайно)
          </Button>
        )}
      </div>
      {error && <p className="text-xs text-error-primary">{error}</p>}
    </section>
  );
}
