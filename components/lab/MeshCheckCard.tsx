"use client";

// Карточка страницы проверки мешей (T-20261112-118, макет `.t118-mockup`): фото товара | снимок модели (телефон — друг под другом),
// оба увеличиваются; «ок» / «брак» — повторное нажатие снимает; комментарий сохраняется сам (MeshCheckNote).
// Сеть — lib/mesh-audit/check-client.ts; правила нажатий — lib/mesh-audit/marks.ts.

import { useRef } from "react";
import { checkStateLine } from "@/lib/mesh-audit/marks";
import type { NoteSaver } from "@/lib/mesh-audit/note-saver";
import type { AuditItemView } from "@/lib/mesh-audit/types";
import { MeshCheckNote } from "./MeshCheckNote";
import { MeshCheckPresses } from "./MeshCheckPresses";
import { useReviewer } from "./MeshCheckReviewer";
import { useMeshPress } from "./useMeshPress";

export type ZoomWhich = "photo" | "model";

interface Props {
  item: AuditItemView;
  onZoom: (which: ZoomWhich) => void;
  onChange: (item: AuditItemView) => void;
}

const LOUPE = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-4-4M11 8v6M8 11h6" />
  </svg>
);

function Pic({ src, label, photo, onOpen }: { src: string | null; label: string; photo?: boolean; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!src}
      aria-label={src ? `Увеличить: ${label}` : `${label}: нет картинки`}
      className={`relative aspect-[4/3] w-full cursor-zoom-in overflow-hidden rounded-lg sm:aspect-square ${
        photo ? "bg-primary ring-1 ring-secondary ring-inset" : "bg-secondary"
      }`}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" className="h-full w-full object-contain" loading="lazy" />
      ) : (
        <span className="flex h-full items-center justify-center text-sm text-tertiary">снимка ещё нет</span>
      )}
      <span className="absolute top-1.5 left-1.5 rounded-md bg-primary px-1.5 py-0.5 text-xs font-semibold text-secondary ring-1 ring-secondary">
        {label}
      </span>
      {src && (
        <span className="absolute right-1.5 bottom-1.5 grid size-7 place-items-center rounded-lg bg-primary text-secondary ring-1 ring-secondary">
          {LOUPE}
        </span>
      )}
    </button>
  );
}

export function MeshCheckCard({ item, onZoom, onChange }: Props) {
  const reviewer = useReviewer();
  const note = useRef<NoteSaver | null>(null);
  const { busy, error, press } = useMeshPress(item, reviewer, onChange, async () => {
    if (note.current?.pending()) await note.current.flush();
  });
  const line = checkStateLine(item);

  const border = item.mark === "ok" ? "ring-fg-success-secondary" : item.mark === "bad" ? "ring-error_subtle" : "ring-secondary";
  return (
    <section className={`flex flex-col gap-2.5 rounded-xl bg-primary p-3 ring-1 ring-inset ${border}`} data-sku={item.sku} id={`c${item.id}`}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Pic src={item.imageUrl} label="фото" photo onOpen={() => onZoom("photo")} />
        <Pic src={item.posterHdUrl ?? item.posterUrl} label="модель" onOpen={() => onZoom("model")} />
      </div>
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold text-primary">{item.name || item.sku}</span>
        <span className="text-xs text-tertiary">
          {item.sku}
          {item.variantsNote ? ` · ${item.variantsNote.split(":")[0]}` : ""}
        </span>
      </div>
      <MeshCheckPresses mark={item.mark} busy={busy} onPress={press} />
      <MeshCheckNote item={item} reviewer={reviewer} saverRef={note} />
      {line && <span className={`text-xs ${line.tone === "bad" ? "text-error-primary" : "text-tertiary"}`}>{line.text}</span>}
      {error && <p className="text-xs text-error-primary">{error}</p>}
    </section>
  );
}
