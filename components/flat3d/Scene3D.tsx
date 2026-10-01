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
  /** Предмет, который сейчас передвигают. Пока он задан, перетаскивание двигает ЕГО, не камеру. */
  movingSlotId?: string | null;
  /** Можно ли поставить предмет в эту точку — решает чистая проверка в `lib/configurator/placement`. */
  canPlace?: (slotId: string, to: { x: number; y: number; rot: number }) => boolean;
  /** Предмет отпустили: запомнить новое место. */
  onMoveCommit?: (slotId: string, to: { x: number; y: number; rot: number }) => void;
  /** Перемещение отменено (Escape) — вернуть как было. */
  onMoveCancel?: () => void;
  hintText: string;
  loadingText: string;
  noWebglText: string;
  retryText: string;
}

export function Scene3D(props: Scene3DProps): React.ReactElement {
  const { apartment, catalogue, scene, lite, roomId, onPickSlot, onRoomChange, onReady } = props;
  const { hintText, loadingText, noWebglText, retryText } = props;
  const { movingSlotId = null, canPlace, onMoveCommit, onMoveCancel } = props;
  // можно ли поставить предмет там, где он сейчас: от этого зависит и цвет подсветки,
  // и доступность кнопки «Поставить» — молча не срабатывающая кнопка выглядит как поломка
  const [dropOk, setDropOk] = useState(true);
  const { selectedSlotId, topView = false, bottomInsetPx = 0 } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewerRef = useRef<FlatViewer | null>(null);
  const dragRef = useRef<{ x: number; y: number; moved: number; id: number } | null>(null);
  const framedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [progress, setProgress] = useState(0);
  // первый показ закрываем большим экраном загрузки, дальше — только тонкой подсказкой:
  // комнаты догружаются на ходу, и накрывать ими всю сцену нельзя
  const [firstLoadDone, setFirstLoadDone] = useState(false);
  const [hintClosed, setHintClosed] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem("remlab.flat3d.hint") === "closed") setHintClosed(true);
    } catch {
      /* приватный режим — показываем подсказку как обычно */
    }
  }, []);
  const [attempt, setAttempt] = useState(0);

  // Подсказка сама не исчезает: она маленькая, стоит вверху и не мешает. Закрывает её человек
  // крестиком — так понятнее, чем «подождите, и она пропадёт».

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
          // комната сменилась на ходу — запоминаем, чтобы НЕ телепортировать камеру обратно
          onRoomChange: (id: string | null) => {
            roomFromWalkRef.current = id;
            onRoomChange(id);
          },
          // честный процент: человеку на медленном телефоне нужно видеть, что идёт загрузка,
          // а не пустой экран (референс конкурента, владелец 30.09)
          onProgress: (loaded, total) => {
            if (cancelled) return;
            const p = total > 0 ? Math.min(1, loaded / total) : 1;
            setProgress(p);
            if (p >= 1) setFirstLoadDone(true);
          },
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

  // ПЕРЕВОД КАМЕРЫ В КОМНАТУ — только когда комнату выбрал ЧЕЛОВЕК (список, план, вид сверху).
  // Если комната сменилась потому, что он сам в неё зашёл, камеру трогать нельзя: при подходе к
  // проёму сцена «дёргала» человека обратно в середину комнаты, и выйти в коридор было
  // невозможно (жалоба владельца 30.09 «проходы не работают» — причина оказалась здесь).
  const roomFromWalkRef = useRef<string | null>(null);
  useEffect(() => {
    if (!ready || !roomId) return;
    if (roomFromWalkRef.current === roomId) return;
    viewerRef.current?.goToRoom(roomId);
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

  // РЕЖИМ ПЕРЕМЕЩЕНИЯ. Пока предмет «взят», тот же жест двигает ЕГО, а не камеру — иначе
  // попытка подвинуть диван разворачивала бы комнату (арбитраж жестов, разбор советника 30.09).
  const dragItem = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const viewer = viewerRef.current;
      if (!viewer || !movingSlotId) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const pt = viewer.floorPoint(e.clientX, e.clientY, rect);
      if (!pt) return;
      const draft = viewer.moveDraft();
      const rot = draft?.rot ?? 0;
      const ok = canPlace ? canPlace(movingSlotId, { x: pt.x, y: pt.y, rot }) : true;
      setDropOk(ok);
      viewer.moveDraftTo(pt.x, pt.y, ok);
    },
    [movingSlotId, canPlace],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
      dragRef.current = { x: e.clientX, y: e.clientY, moved: 0, id: e.pointerId };
      if (movingSlotId) dragItem(e);
    },
    [movingSlotId, dragItem],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const d = dragRef.current;
      if (!d || d.id !== e.pointerId) return;
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      d.x = e.clientX;
      d.y = e.clientY;
      d.moved += Math.abs(dx) + Math.abs(dy);
      if (movingSlotId) {
        dragItem(e);
        return;
      }
      viewerRef.current?.look(dx, dy);
    },
    [movingSlotId, dragItem],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const d = dragRef.current;
      dragRef.current = null;
      const viewer = viewerRef.current;
      if (!d || !viewer) return;
      if (movingSlotId) {
        // отпустили предмет: ставим, если место подходит; если нет — остаёмся в режиме,
        // подсветка красная, человек тянет дальше
        const draft = viewer.moveDraft();
        if (draft && (!canPlace || canPlace(movingSlotId, draft))) {
          const done = viewer.endMove();
          if (done) onMoveCommit?.(done.slotId, { x: done.x, y: done.y, rot: done.rot });
        }
        return;
      }
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
    [onPickSlot, movingSlotId, canPlace, onMoveCommit],
  );

  // вход и выход из режима перемещения + Escape как отмена
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    if (movingSlotId) {
      viewer.beginMove(movingSlotId);
      const d = viewer.moveDraft();
      setDropOk(d && canPlace ? canPlace(movingSlotId, d) : true);
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && movingSlotId) {
        viewer.cancelMove();
        onMoveCancel?.();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [movingSlotId, ready, onMoveCancel, canPlace]);

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
      {(!ready || progress < 1) && !firstLoadDone ? (
        error ? null : (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-secondary">
            <p className="text-sm text-secondary">{loadingText}</p>
            <div className="h-1.5 w-56 overflow-hidden rounded-full bg-primary">
              <div
                className="h-full rounded-full bg-brand-solid"
                style={{ width: `${Math.round(progress * 100)}%`, transition: "width 200ms linear" }}
              />
            </div>
            <p className="text-xs text-tertiary" data-flat3d="progress">
              {Math.round(progress * 100)}%
            </p>
          </div>
        )
      ) : null}

      {/* Пока предмет «взят»: повернуть, поставить, отменить. Кнопки — обычные HTML-кнопки
          поверх картинки: их находит тест, они не пляшут при повороте камеры и всегда ≥44 px. */}
      {movingSlotId ? (
        <div
          className="pointer-events-none absolute inset-x-0 flex justify-center"
          style={{ zIndex: 12, bottom: 12 + (props.bottomInsetPx ?? 0) + 76 }}
        >
          <div className="pointer-events-auto flex items-center gap-1.5 rounded-2xl bg-primary/95 p-1.5 shadow-md ring-1 ring-inset ring-secondary backdrop-blur-md">
            <button
              type="button"
              aria-label="Повернуть влево"
              className="min-h-11 min-w-11 rounded-xl bg-secondary text-lg text-primary"
              onClick={() => {
                const v = viewerRef.current;
                const d = v?.moveDraft();
                if (!v || !d) return;
                const next = { ...d, rot: (d.rot - 15 + 360) % 360 };
                const ok = canPlace ? canPlace(movingSlotId, next) : true;
                setDropOk(ok);
                v.rotateDraftBy(-15, ok);
              }}
            >
              ↺
            </button>
            <button
              type="button"
              aria-label="Повернуть вправо"
              className="min-h-11 min-w-11 rounded-xl bg-secondary text-lg text-primary"
              onClick={() => {
                const v = viewerRef.current;
                const d = v?.moveDraft();
                if (!v || !d) return;
                const next = { ...d, rot: (d.rot + 15) % 360 };
                const ok = canPlace ? canPlace(movingSlotId, next) : true;
                setDropOk(ok);
                v.rotateDraftBy(15, ok);
              }}
            >
              ↻
            </button>
            <button
              type="button"
              disabled={!dropOk}
              title={dropOk ? undefined : "Здесь не встанет: место занято или предмет выходит за комнату"}
              className="min-h-11 rounded-xl bg-brand-solid px-4 text-sm font-semibold text-white disabled:opacity-50"
              onClick={() => {
                const v = viewerRef.current;
                const d = v?.moveDraft();
                if (!v || !d) return;
                if (canPlace && !canPlace(movingSlotId, d)) return;
                const done = v.endMove();
                if (done) onMoveCommit?.(done.slotId, { x: done.x, y: done.y, rot: done.rot });
              }}
            >
              {dropOk ? "Поставить" : "Не встанет"}
            </button>
            <button
              type="button"
              className="min-h-11 rounded-xl px-3 text-sm text-secondary"
              onClick={() => {
                viewerRef.current?.cancelMove();
                onMoveCancel?.();
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      {firstLoadDone && progress < 1 && !error ? (
        <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-xs text-secondary ring-1 ring-inset ring-secondary">
          {loadingText} · {Math.round(progress * 100)}%
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

      {/* ПОДСКАЗКА — ВВЕРХУ, отдельной карточкой с крестиком (владелец 30.09: «сделай красиво
          вверху, на полупрозрачном фоне, с крестиком, как окно»). Внизу она налезала на кнопки
          ходьбы. Закрыли — больше не показываем: решение помним в браузере. */}
      {!error && ready && !hintClosed ? (
        <div
          className="pointer-events-auto absolute left-1/2 flex max-w-[92%] -translate-x-1/2 items-start gap-2 rounded-2xl px-4 py-2.5 shadow-sm ring-1 ring-inset ring-secondary"
          style={{ top: 12, zIndex: 11, background: "color-mix(in srgb, var(--color-bg-primary) 82%, transparent)", backdropFilter: "blur(8px)" }}
        >
          <p className="text-xs leading-relaxed text-secondary">{hintText}</p>
          <button
            type="button"
            aria-label="Закрыть подсказку"
            onClick={() => {
              setHintClosed(true);
              try {
                window.localStorage.setItem("remlab.flat3d.hint", "closed");
              } catch {
                /* приватный режим — подсказка просто вернётся в следующий раз */
              }
            }}
            className="-mr-1 -mt-0.5 shrink-0 rounded-lg px-2 py-1 text-sm text-tertiary hover:bg-secondary"
          >
            ✕
          </button>
        </div>
      ) : null}
    </div>
  );
}
