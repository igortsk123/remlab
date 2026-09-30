"use client";

// Экранное управление прогулкой.
//
// ЗАЧЕМ: клавиш WASD не знает большинство, на телефоне их нет вовсе, а мышью «оглядеться» умеют
// тоже не все (владелец 30.09). Кнопки — единственный способ, понятный любому.
//
// КАК УСТРОЕНО (сделано по разбору туров и мобильных игр, 30.09):
// 1. ОДИН блок ВНИЗУ ПО ЦЕНТРУ — туда сам тянется большой палец и туда же смотрит глаз;
//    прежние кнопки в левом нижнем углу владелец назвал неудобными.
// 2. Боковые стрелки ПОВОРАЧИВАЮТ, а не шагают вбок: в квартире нужно повернуться и пойти,
//    приставной шаг здесь почти не нужен (он остался на клавишах A/D).
// 3. Кнопок ровно четыре: больше пяти управляющих элементов на экране человек уже не разбирает.
// 4. Полупрозрачные и с размытием под собой — сквозь них видно комнату; при наведении и нажатии
//    становятся плотными.
// 5. САМИ ГАСНУТ через 4 секунды без использования и возвращаются от любого движения мыши,
//    касания или клавиши: «не мешать обзору, но помогать».
// 6. Размер ≥ 44 px (на телефоне 60) — иначе не попасть пальцем.

import { useCallback, useEffect, useRef, useState } from "react";

interface WalkPadProps {
  onHold: (code: string, down: boolean) => void;
  onTurn: (deltaDeg: number) => void;
  compact?: boolean;
  /** На сколько поднять кнопки, когда снизу открыта панель выбора. */
  liftPx?: number;
}

const HOLD_MS = 90;
const IDLE_MS = 4000;

export function WalkPad({ onHold, onTurn, compact = false, liftPx = 0 }: WalkPadProps) {
  const heldRef = useRef<Set<string>>(new Set());
  const turnRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [dim, setDim] = useState(false);
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const wake = useCallback(() => {
    setDim(false);
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => setDim(true), IDLE_MS);
  }, []);

  // гасим кнопки в покое и будим от любого действия человека
  useEffect(() => {
    wake();
    const on = () => wake();
    window.addEventListener("pointermove", on, { passive: true });
    window.addEventListener("pointerdown", on, { passive: true });
    window.addEventListener("keydown", on);
    return () => {
      window.removeEventListener("pointermove", on);
      window.removeEventListener("pointerdown", on);
      window.removeEventListener("keydown", on);
      if (idleRef.current) clearTimeout(idleRef.current);
    };
  }, [wake]);

  // отпустить всё при уходе со страницы: иначе человек «уезжает» сам по себе
  useEffect(() => {
    const held = heldRef.current;
    return () => {
      for (const code of held) onHold(code, false);
      held.clear();
      if (turnRef.current) clearInterval(turnRef.current);
    };
  }, [onHold]);

  const press = useCallback(
    (code: string) => (e: React.PointerEvent) => {
      e.preventDefault();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      heldRef.current.add(code);
      onHold(code, true);
      wake();
    },
    [onHold, wake],
  );

  const release = useCallback(
    (code: string) => () => {
      heldRef.current.delete(code);
      onHold(code, false);
    },
    [onHold],
  );

  const turnStart = useCallback(
    (deg: number) => (e: React.PointerEvent) => {
      e.preventDefault();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      onTurn(deg);
      wake();
      if (turnRef.current) clearInterval(turnRef.current);
      turnRef.current = setInterval(() => onTurn(deg), HOLD_MS);
    },
    [onTurn, wake],
  );

  const turnStop = useCallback(() => {
    if (turnRef.current) clearInterval(turnRef.current);
    turnRef.current = null;
  }, []);

  const size = compact ? 60 : 52;
  const btn =
    "flex items-center justify-center rounded-2xl bg-primary text-primary ring-1 ring-inset ring-secondary " +
    "backdrop-blur-md active:bg-brand-solid active:text-white select-none touch-none shadow-sm";
  const btnStyle = { width: size, height: size, fontSize: compact ? 22 : 19, opacity: 0.92 };

  // z-0: карточка предмета (z-20) обязана быть ВЫШЕ — иначе кнопки ходьбы перехватывают клики
  // по «Заменить», когда предмет оказался в нижней части кадра (поймано CI 29.09).
  return (
    <div
      className="pointer-events-none absolute inset-x-0 flex justify-center"
      style={{
        zIndex: 5,
        bottom: 12 + liftPx,
        opacity: dim ? 0.3 : 0.92,
        transition: "opacity 400ms ease",
      }}
      onPointerEnter={wake}
    >
      <div className="pointer-events-auto grid grid-cols-3 gap-1.5" style={{ justifyItems: "center" }}>
        <button
          type="button"
          aria-label="Повернуться влево"
          className={btn}
          style={btnStyle}
          onPointerDown={turnStart(-9)}
          onPointerUp={turnStop}
          onPointerLeave={turnStop}
          onPointerCancel={turnStop}
        >
          ↰
        </button>
        <button
          type="button"
          aria-label="Идти вперёд"
          className={btn}
          style={btnStyle}
          onPointerDown={press("KeyW")}
          onPointerUp={release("KeyW")}
          onPointerLeave={release("KeyW")}
          onPointerCancel={release("KeyW")}
        >
          ↑
        </button>
        <button
          type="button"
          aria-label="Повернуться вправо"
          className={btn}
          style={btnStyle}
          onPointerDown={turnStart(9)}
          onPointerUp={turnStop}
          onPointerLeave={turnStop}
          onPointerCancel={turnStop}
        >
          ↱
        </button>
        <span />
        <button
          type="button"
          aria-label="Отойти назад"
          className={btn}
          style={btnStyle}
          onPointerDown={press("KeyS")}
          onPointerUp={release("KeyS")}
          onPointerLeave={release("KeyS")}
          onPointerCancel={release("KeyS")}
        >
          ↓
        </button>
        <span />
      </div>
    </div>
  );
}
