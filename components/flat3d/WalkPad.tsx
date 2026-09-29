"use client";

// Экранное управление прогулкой: вперёд/назад/шаг вбок и поворот.
//
// ЗАЧЕМ: клавиши WASD знает не каждый, а на телефоне их нет вовсе — там можно было только
// «идти к точке», то есть ВПЕРЁД. Владелец 29.09: «при навигации надо иметь возможность назад
// отойти». Кнопки решают это на любом устройстве и видны постоянно, в отличие от подсказки.

import { useCallback, useEffect, useRef } from "react";

interface WalkPadProps {
  onHold: (code: string, down: boolean) => void;
  onTurn: (deltaDeg: number) => void;
  compact?: boolean;
}

const HOLD_MS = 90;

export function WalkPad({ onHold, onTurn, compact = false }: WalkPadProps) {
  const heldRef = useRef<Set<string>>(new Set());
  const turnRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    },
    [onHold],
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
      onTurn(deg);
      if (turnRef.current) clearInterval(turnRef.current);
      turnRef.current = setInterval(() => onTurn(deg), HOLD_MS);
    },
    [onTurn],
  );

  const turnStop = useCallback(() => {
    if (turnRef.current) clearInterval(turnRef.current);
    turnRef.current = null;
  }, []);

  const btn =
    "flex items-center justify-center rounded-xl bg-primary/85 text-primary ring-1 ring-inset ring-secondary " +
    "backdrop-blur-sm active:bg-brand-solid active:text-white select-none touch-none " +
    (compact ? "size-12 text-lg" : "size-14 text-xl");

  // z-0: карточка предмета (z-20) обязана быть ВЫШЕ — иначе кнопки ходьбы перехватывают клики
  // по «Заменить», когда предмет оказался в нижней части кадра (поймано CI 29.09).
  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-3 flex items-end justify-between px-3"
      style={{ zIndex: 5 }}
    >
      <div className="pointer-events-auto grid grid-cols-3 gap-1.5">
        <span />
        <button
          type="button"
          aria-label="Идти вперёд"
          className={btn}
          onPointerDown={press("KeyW")}
          onPointerUp={release("KeyW")}
          onPointerLeave={release("KeyW")}
          onPointerCancel={release("KeyW")}
        >
          ↑
        </button>
        <span />
        <button
          type="button"
          aria-label="Шаг влево"
          className={btn}
          onPointerDown={press("KeyA")}
          onPointerUp={release("KeyA")}
          onPointerLeave={release("KeyA")}
          onPointerCancel={release("KeyA")}
        >
          ←
        </button>
        <button
          type="button"
          aria-label="Отойти назад"
          className={btn}
          onPointerDown={press("KeyS")}
          onPointerUp={release("KeyS")}
          onPointerLeave={release("KeyS")}
          onPointerCancel={release("KeyS")}
        >
          ↓
        </button>
        <button
          type="button"
          aria-label="Шаг вправо"
          className={btn}
          onPointerDown={press("KeyD")}
          onPointerUp={release("KeyD")}
          onPointerLeave={release("KeyD")}
          onPointerCancel={release("KeyD")}
        >
          →
        </button>
      </div>

      <div className="pointer-events-auto flex gap-1.5">
        <button
          type="button"
          aria-label="Повернуться влево"
          className={btn}
          onPointerDown={turnStart(-9)}
          onPointerUp={turnStop}
          onPointerLeave={turnStop}
          onPointerCancel={turnStop}
        >
          ⟲
        </button>
        <button
          type="button"
          aria-label="Повернуться вправо"
          className={btn}
          onPointerDown={turnStart(9)}
          onPointerUp={turnStop}
          onPointerLeave={turnStop}
          onPointerCancel={turnStop}
        >
          ⟳
        </button>
      </div>
    </div>
  );
}
