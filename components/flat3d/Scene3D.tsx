"use client";

// Канвас 3D. Вся работа с WebGL — в `lib/viewer3d/viewer.ts`, здесь только жизненный цикл.
//
// ГРАБЛИ, ЗАЛОЖЕННЫЕ СПЕЦИАЛЬНО:
// 1) three грузится ДИНАМИЧЕСКИМ импортом внутри эффекта — движок не попадает в общий бандл
//    страницы (в проекте это первый code-splitting, поэтому пишу явно);
// 2) `reactStrictMode` в dev монтирует эффект дважды — инициализация идемпотентна, а cleanup
//    полностью гасит рендерер (иначе два цикла кадра и утечка контекста);
// 3) на body проекта висит CSS `zoom` (`app/globals.css`), поэтому координаты курсора берём
//    ТОЛЬКО через `getBoundingClientRect()` канваса, никаких offsetWidth.

import { useCallback, useEffect, useRef, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import type { FlatViewer, QualityProfile } from "@/lib/viewer3d/viewer";
import { WalkPad } from "@/components/flat3d/WalkPad";

export interface Scene3DProps {
  apartment: Apartment;
  catalogue: Catalogue;
  scene: ResolvedScene;
  lite: boolean;
  roomId: string | null;
  onPickSlot: (slotId: string | null) => void;
  onRoomChange: (roomId: string | null) => void;
  onReady?: () => void;
  /** Выбранный предмет — его обводим контуром. */
  selectedSlotId: string | null;
  /** Вид сверху под углом вместо прогулки. */
  topView?: boolean;
  /** Сколько пикселей снизу занято панелью выбора — на столько поднимаем кнопки ходьбы. */
  bottomInsetPx?: number;
  hintText: string;
  loadingText: string;
  noWebglText: string;
  retryText: string;
}

export function Scene3D(props: Scene3DProps): React.ReactElement {
  const { apartment, catalogue, scene, lite, roomId, onPickSlot, onRoomChange, onReady } = props;
  const { hintText, loadingText, noWebglText, retryText } = props;
  const { selectedSlotId, topView = false, bottomInsetPx = 0 } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewerRef = useRef<FlatViewer | null>(null);
  const dragRef = useRef<{ x: number; y: number; moved: number; id: number } | null>(null);
  const framedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [hintDone, setHintDone] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setHintDone(true), 7000);
    return () => clearTimeout(t);
  }, []);

  // создание/уничтожение сцены: зависит только от профиля качества
  useEffect(() => {
    let cancelled = false;
    const canvas = canvasRef.current;
    if (!canvas) return;

    (async () => {
      try {
        const mod = await import("@/lib/viewer3d/viewer");
        if (cancelled) return;
        const quality: QualityProfile = lite ? mod.LITE_QUALITY : mod.DESKTOP_QUALITY;
        const viewer = new mod.FlatViewer(canvas, apartment, catalogue, quality, {
          onRoomChange,
        });
        viewerRef.current = viewer;
        // отладочный доступ: e2e и ручная проверка спрашивают у сцены её состояние
        // (сколько объектов, где камера) — без этого «чёрный экран» диагностируется вслепую
        (window as unknown as { __flatViewer?: unknown }).__flatViewer = viewer;
        const rect = canvas.getBoundingClientRect();
        viewer.setSize(Math.max(320, rect.width), Math.max(240, rect.height));
        viewer.start();
        setReady(true);
        onReady?.();
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setReady(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      viewerRef.current?.dispose();
      viewerRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- пересоздаём сцену при смене качества и по кнопке «повторить»
  }, [lite, apartment, catalogue, attempt]);

  // конфигурация изменилась — обновляем коробку и предметы
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    viewer.buildShell(scene);
    void viewer.syncObjects(scene).then(() => {
      // ПЕРВЫЙ кадр ставим ПОСЛЕ загрузки мебели: точка обзора выбирается с учётом того,
      // где стоят предметы, а при старте их ещё нет — камера оказывалась внутри дивана
      if (!framedRef.current && roomId) {
        framedRef.current = true;
        viewerRef.current?.goToRoom(roomId);
      }
    });
  }, [scene, ready, roomId]);

  useEffect(() => {
    if (ready && roomId) viewerRef.current?.goToRoom(roomId);
  }, [roomId, ready]);

  // выделение приходит снаружи (кликом по сцене или выбором в панели)
  useEffect(() => {
    if (ready) viewerRef.current?.highlight(selectedSlotId);
  }, [selectedSlotId, ready]);

  // вид сверху ↔ бродилка
  useEffect(() => {
    if (ready) viewerRef.current?.setViewMode(topView ? "top" : "walk");
  }, [topView, ready]);

  // размер канваса
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      const r = canvas.getBoundingClientRect();
      viewerRef.current?.setSize(Math.max(320, r.width), Math.max(240, r.height));
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []);

  // клавиатура — только когда канвас в фокусе или мышь над ним
  useEffect(() => {
    const down = (e: KeyboardEvent): void => {
      if (!viewerRef.current) return;
      if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "ShiftLeft"].includes(e.code)) {
        viewerRef.current.keyDown(e.code);
        if (e.code.startsWith("Arrow")) e.preventDefault();
      }
    };
    const up = (e: KeyboardEvent): void => viewerRef.current?.keyUp(e.code);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const holdKey = useCallback((code: string, down: boolean) => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (down) viewer.keyDown(code);
    else viewer.keyUp(code);
  }, []);

  const turnBy = useCallback((deg: number) => {
    // `look` принимает сдвиг курсора в пикселях (0.22° на пиксель) — переводим градусы
    viewerRef.current?.look(deg / 0.22, 0);
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, moved: 0, id: e.pointerId };
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    d.x = e.clientX;
    d.y = e.clientY;
    d.moved += Math.abs(dx) + Math.abs(dy);
    viewerRef.current?.look(dx, dy);
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const d = dragRef.current;
      dragRef.current = null;
      const viewer = viewerRef.current;
      if (!d || !viewer) return;
      if (d.moved > 12) return; // это был осмотр, а не выбор
      const rect = e.currentTarget.getBoundingClientRect();
      const hit = viewer.pick(e.clientX, e.clientY, rect);
      if (hit.slotId) {
        onPickSlot(hit.slotId);
        viewer.highlight(hit.slotId);
        return;
      }
      if (hit.point) {
        viewer.goTo(hit.point.x, hit.point.y);
        onPickSlot(null);
        viewer.highlight(null);
      }
    },
    [onPickSlot],
  );

  return (
    <div className="relative h-full w-full">
      <canvas
        ref={canvasRef}
        className="touch-none rounded-xl bg-secondary"
        style={{ width: "100%", height: "100%", display: "block" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={(e) => viewerRef.current?.zoom(e.deltaY * 0.6)}
        aria-label="3D-вид квартиры"
        role="img"
      />
      {/* СОСТОЯНИЯ ЭКРАНА (правило ui-rules): загрузка, отказ WebGL с повтором, готово. */}
      {!ready && !error ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl bg-secondary">
          <p className="rounded-lg bg-primary px-4 py-2 text-sm text-secondary ring-1 ring-inset ring-secondary">
            {loadingText}
          </p>
        </div>
      ) : null}

      {error ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-secondary p-4 text-center">
          <p className="max-w-sm text-sm text-secondary">{noWebglText}</p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            className="min-h-11 rounded-lg bg-brand-solid px-4 text-sm font-semibold text-white"
          >
            {retryText}
          </button>
        </div>
      ) : null}

      {ready && !error ? (
        <WalkPad onHold={holdKey} onTurn={turnBy} compact={lite} liftPx={bottomInsetPx} />
      ) : null}

      {/* подсказка уходит через 7 секунд: на телефоне она закрывает треть комнаты */}
      <p
        hidden={Boolean(error) || hintDone || !ready}
        className="pointer-events-none absolute inset-x-3 rounded-lg bg-primary/90 px-3 py-2 text-center text-xs text-secondary ring-1 ring-inset ring-secondary" style={{ bottom: 76 }}
      >
        {hintText}
      </p>
    </div>
  );
}
