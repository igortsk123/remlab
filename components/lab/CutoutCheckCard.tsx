"use client";

// Карточка проверки вырезки (T-20261119-104): фото магазина | вырезка на шахматке | вырезка на тёмном фоне (телефон — друг под другом),
// каждая увеличивается; «Ок» / «Не ок» — повтор снимает; «что не так» сохраняется само. Подписи парой RU/EN.

import { useRef } from "react";
import { L, type Pair } from "@/lib/cutout-check/rules";
import type { CutoutItemView } from "@/lib/cutout-check/types";
import type { NoteSaver } from "@/lib/mesh-audit/note-saver";
import { CutoutCheckNote } from "./CutoutCheckNote";
import { CutoutCheckPresses } from "./CutoutCheckPresses";
import { useReviewer } from "./MeshCheckReviewer";
import { useCutoutPress } from "./useCutoutPress";

export type Bg = "photo" | "checker" | "dark";
export interface ZoomTarget {
  src: string;
  bg: Bg;
  label: Pair;
}

// шахматка и тёмный фон — прямо на картинке, чтобы дыры, ореол и остатки фона были видны сразу
const BG_STYLE: Record<Bg, string> = {
  photo: "bg-primary",
  checker: "[background:repeating-conic-gradient(#d4d4d8_0%_25%,#f4f4f5_0%_50%)_50%/16px_16px]",
  dark: "bg-[#1b1b1f]",
};

export function Pic({ src, bg, label, onOpen }: { src: string | null; bg: Bg; label: Pair; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!src}
      aria-label={src ? `${label.ru} / ${label.en}: ${L.zoomHint.ru}` : `${label.ru}: ${L.noPic.ru}`}
      className={`relative aspect-[4/3] w-full cursor-zoom-in overflow-hidden rounded-lg ring-1 ring-secondary ring-inset sm:aspect-square ${BG_STYLE[bg]}`}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" className="h-full w-full object-contain" loading="lazy" />
      ) : (
        <span className="flex h-full items-center justify-center text-sm text-tertiary">
          {L.noPic.ru} / {L.noPic.en}
        </span>
      )}
      <span className="absolute top-1.5 left-1.5 rounded-md bg-primary px-1.5 py-0.5 text-xs font-semibold text-secondary ring-1 ring-secondary">
        {label.ru} · {label.en}
      </span>
    </button>
  );
}

interface Props {
  item: CutoutItemView;
  onZoom: (t: ZoomTarget) => void;
  onChange: (item: CutoutItemView) => void;
}

export function CutoutCheckCard({ item, onZoom, onChange }: Props) {
  const reviewer = useReviewer();
  const note = useRef<NoteSaver | null>(null);
  const { busy, error, press } = useCutoutPress(item, reviewer, onChange, async () => {
    if (note.current?.pending()) await note.current.flush();
  });
  const border = item.mark === "ok" ? "ring-fg-success-secondary" : item.mark === "bad" ? "ring-error_subtle" : "ring-secondary";
  const open = (src: string | null, bg: Bg, label: Pair) => () => src && onZoom({ src, bg, label });
  const warn = typeof item.info?.verdict === "string" && item.info.verdict !== "ok" ? String(item.info.verdict) : null;

  return (
    <section className={`flex flex-col gap-2.5 rounded-xl bg-primary p-3 ring-1 ring-inset ${border}`} data-sku={item.sku} id={`c${item.id}`}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Pic src={item.photoUrl} bg="photo" label={L.photo} onOpen={open(item.photoUrl, "photo", L.photo)} />
        <Pic src={item.cutUrl} bg="checker" label={L.cutChecker} onOpen={open(item.cutUrl, "checker", L.cutChecker)} />
        <Pic src={item.cutUrl} bg="dark" label={L.cutDark} onOpen={open(item.cutUrl, "dark", L.cutDark)} />
      </div>
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold text-primary">{item.name || item.sku}</span>
        <span className="text-xs text-tertiary">
          {item.nameEn ? `${item.nameEn} · ` : ""}
          {item.sku}
          {item.shop ? ` · ${item.shop}` : ""}
        </span>
        {warn && <span className="text-xs text-tertiary">цепочка: {warn}</span>}
      </div>
      <CutoutCheckPresses mark={item.mark} busy={busy} onPress={press} />
      <CutoutCheckNote item={item} reviewer={reviewer} saverRef={note} />
      {error && <p className="text-xs text-error-primary">{error}</p>}
    </section>
  );
}
