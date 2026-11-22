"use client";

// Карточка проверки вырезки (T-20261119-104): фото магазина | вырезка на шахматке | вырезка на тёмном фоне (телефон — друг под другом),
// каждая увеличивается; одна кнопка «Не ок» (без отметки = ок), «что не так» — только после неё, сохраняется само; «просмотрено» — когда карточка
// побыла на экране ≥ 1 с. Подписи парой RU/EN.

import { useCallback, useRef } from "react";
import { sendView } from "@/lib/cutout-check/client";
import { L, type Pair } from "@/lib/cutout-check/rules";
import type { CutoutItemView } from "@/lib/cutout-check/types";
import type { NoteSaver } from "@/lib/mesh-audit/note-saver";
import { CutoutCheckNote } from "./CutoutCheckNote";
import { CutoutCheckPresses } from "./CutoutCheckPresses";
import { useReviewer } from "./MeshCheckReviewer";
import { useCutoutPress } from "./useCutoutPress";
import { useSeenOnScreen } from "./useSeenOnScreen";

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

export function Pic({ src, bg, label, onOpen, eager }: { src: string | null; bg: Bg; label: Pair; onOpen: () => void; eager?: boolean }) {
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
        <img src={src} alt="" className="h-full w-full object-contain" loading={eager ? "eager" : "lazy"} decoding="async" />
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
  eager?: boolean; // первые карточки страницы грузят картинки сразу (без ленивой загрузки); место держит рамка aspect-[4/3]
  onView: (id: number, generationKey: string) => void; // «просмотрено» дошло до сервера: доска сама подмешает в свежее состояние карточки
}

export function CutoutCheckCard({ item, onZoom, onChange, onView, eager }: Props) {
  const reviewer = useReviewer();
  const note = useRef<NoteSaver | null>(null);
  const { busy, error, press } = useCutoutPress(item, reviewer, onChange, async () => {
    if (note.current?.pending()) await note.current.flush();
  });
  const bad = item.mark === "bad";
  const box = useRef<HTMLElement | null>(null);
  const seen = useCallback(() => {
    void sendView(item, reviewer).then((ok) => ok && onView(item.id, item.generationKey));
  }, [item, reviewer, onView]);
  useSeenOnScreen(box, !item.viewedAt && !bad && reviewer !== "", seen);
  const border = bad ? "" : "ring-1 ring-secondary";
  const open = (src: string | null, bg: Bg, label: Pair) => () => src && onZoom({ src, bg, label });
  const warn = typeof item.info?.verdict === "string" && item.info.verdict !== "ok" ? String(item.info.verdict) : null;

  return (
    <section ref={box} style={bad ? { boxShadow: "inset 0 0 0 3px var(--color-bg-error-solid)" } : undefined} className={`flex flex-col gap-2.5 rounded-xl bg-primary p-3 ring-inset ${border}`} data-sku={item.sku} id={`c${item.id}`}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Pic src={item.photoUrl} bg="photo" label={L.photo} onOpen={open(item.photoUrl, "photo", L.photo)} eager={eager} />
        <Pic src={item.cutUrl} bg="checker" label={L.cutChecker} onOpen={open(item.cutUrl, "checker", L.cutChecker)} eager={eager} />
        <Pic src={item.cutUrl} bg="dark" label={L.cutDark} onOpen={open(item.cutUrl, "dark", L.cutDark)} eager={eager} />
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
      {bad && <CutoutCheckNote item={item} reviewer={reviewer} saverRef={note} />}
      {error && <p className="text-xs text-error-primary">{error}</p>}
    </section>
  );
}
