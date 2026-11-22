"use client";

// «Просмотрено» без кликов (владелец, правка директора 19.11): карточка побыла на экране ≥ 1 с. Следим IntersectionObserver'ом: видна заметная
// часть (≥ 200 px высоты или половина карточки) и вкладка не скрыта — запускаем таймер; ушла с экрана раньше — сбрасываем. Один раз на карточку и вырезку.

import { useEffect, useRef, type RefObject } from "react";
import { VIEW_MS } from "@/lib/cutout-check/rules";

const THRESHOLDS = Array.from({ length: 21 }, (_, i) => i / 20);

export function useSeenOnScreen(ref: RefObject<HTMLElement | null>, enabled: boolean, onSeen: () => void): void {
  const cb = useRef(onSeen);
  cb.current = onSeen;
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el || typeof IntersectionObserver === "undefined") return;
    let timer: number | null = null;
    let done = false;
    const stop = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    const start = () => {
      if (timer !== null || done) return;
      timer = window.setTimeout(() => {
        timer = null;
        if (document.visibilityState !== "visible") return;
        done = true;
        cb.current();
      }, VIEW_MS);
    };
    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[entries.length - 1];
        if (!e) return;
        const seen = e.isIntersecting && (e.intersectionRect.height >= 200 || e.intersectionRatio >= 0.5);
        if (seen && document.visibilityState === "visible") start();
        else stop();
      },
      { threshold: THRESHOLDS },
    );
    io.observe(el);
    const onVis = () => document.visibilityState !== "visible" && stop();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [ref, enabled]);
}
