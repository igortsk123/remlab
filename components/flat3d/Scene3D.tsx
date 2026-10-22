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
import { WalkPad, walkPadZone } from "@/components/flat3d/WalkPad";

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
  /** Кнопки у выбранного предмета (flat3d-sims-ux C1): «Заменить» открывает варианты, «Передвинуть» — перемещение. */
  onItemOptions?: () => void;
  onItemMove?: (slotId: string) => void;
  /** «Убрать» предмет; undefined у встроенного — кнопки нет. */
  onItemRemove?: (slotId: string) => void;
  itemLabels?: { options: string; move: string; remove: string };
  /** Подписи кнопки «показать/скрыть управление» (D4). */
  padLabels?: { show: string; hide: string };
  /** Стрелки ходьбы не показывать: на телефоне открыта панель выбора, и кадр короткий (flat3d-375-overlaps). */
  padSuppressed?: boolean;
  /** Точки на заменяемых предметах текущей комнаты (D6). */
  spots?: Spot[];
  hintText: string;
  /** Телефон: подсказка — одна строка, не плашка (demo-05 п.6). */
  hintCompact?: boolean;
  loadingText: string;
  /** Экран первой загрузки (flat3d-sims-ux D8): заголовок, строка «что тут можно», подписи этапов по проценту. */
  loadingTitle?: string;
  loadingHint?: string;
  loadingStages?: readonly [string, string, string];
  /** Логотип застройщика на экране загрузки (D8); нет — без логотипа. */
  loadingLogo?: string;
  noWebglText: string;
  retryText: string;
}

import { ObjectTools } from "@/components/flat3d/ObjectTools";
import { Hotspots, type Spot, type Zones } from "@/components/flat3d/Hotspots";

// ЗОНЫ КАДРА (flat3d-375-overlaps, 21.10): сверху — строка кнопок правой панели (`InfoPanel`), снизу — стрелки ходьбы,
// во «Сверху» — полоса «Войти в комнату» (`FlatConfigurator`). Подписи точек и меню предмета держатся между ними.
const ZONE_TOP = 60; // 8 + кнопка 44 + 8
const ZONE_STRIP = 60; // одна строка кнопок у нижнего края: «Показать управление» или комнаты во «Сверху»
const ZONE_EDGE = 8;

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
  const projectAny = useCallback((id: string) => viewerRef.current?.projectSlot(id) ?? null, []);
  const pickSpot = useCallback((id: string) => {
    onPickSlot(id);
    viewerRef.current?.highlight(id);
  }, [onPickSlot]);
  const projectSelected = useCallback(
    () => (selectedSlotId ? viewerRef.current?.projectSlot(selectedSlotId) ?? null : null),
    [selectedSlotId],
  );
  const [progress, setProgress] = useState(0);
  // первый показ закрываем большим экраном загрузки, дальше — только тонкой подсказкой:
  // комнаты догружаются на ходу, и накрывать ими всю сцену нельзя
  const [firstLoadDone, setFirstLoadDone] = useState(false);
  const [hintClosed, setHintClosed] = useState(false);
  // ПОДСКАЗКА УХОДИТ САМА (demo-05 п.6, прогон 14.10: плашка висела поверх сцены всю прогулку): через 6 с или по первому
  // действию человека; на этот показ, без записи в браузер — повторно её открывает «?» (справка с роликами)
  const [hintAuto, setHintAuto] = useState(false);
  useEffect(() => {
    if (!ready || hintClosed || hintAuto) return;
    const hide = (): void => setHintAuto(true);
    const t = window.setTimeout(hide, 6000);
    window.addEventListener("pointerdown", hide, { once: true });
    window.addEventListener("keydown", hide, { once: true });
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("pointerdown", hide);
      window.removeEventListener("keydown", hide);
    };
  }, [ready, hintClosed, hintAuto]);
  const [padShown, setPadShown] = useState(true);
  useEffect(() => {
    try {
      if (window.localStorage.getItem("remlab.flat3d.pad") === "hidden") setPadShown(false);
    } catch {
      /* приватный режим — кнопки видны */
    }
  }, []);
  const togglePad = useCallback(() => setPadShown((v) => {
    try {
      window.localStorage.setItem("remlab.flat3d.pad", v ? "hidden" : "shown");
    } catch {
      /* не сохранили — переключение всё равно работает */
    }
    return !v;
  }), []);
  useEffect(() => {
    try {
      if (window.localStorage.getItem("remlab.flat3d.hint") === "closed") setHintClosed(true);
    } catch {
      /* приватный режим — показываем подсказку как обычно */
    }
  }, []);
  const [attempt, setAttempt] = useState(0);

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

  // Повернуть «взятый» предмет на шаг: кнопки ↺ ↻, колесо мыши и поворот двумя пальцами — одно действие
  const rotateDraft = useCallback((deg: number) => {
    const v = viewerRef.current;
    const d = v?.moveDraft();
    if (!v || !d || !movingSlotId) return;
    const next = { ...d, rot: (d.rot + deg + 360) % 360 };
    const ok = canPlace ? canPlace(movingSlotId, next) : true;
    setDropOk(ok);
    v.rotateDraftBy(deg, ok);
  }, [movingSlotId, canPlace]);

  // ДВА ПАЛЬЦА (flat3d-sims-ux D2/C3): щипок приближает вид сверху, поворот двумя пальцами крутит «взятый» предмет
  // шагом 15°. Пока пальцев два, осмотр и выбор не срабатывают — иначе щипок вертел бы камеру и «кликал» по мебели.
  const pointersRef = useRef(new Map<number, { x: number; y: number }>());
  const pinchRef = useRef<{ dist: number; ang: number; acc: number } | null>(null);
  const pinchGeom = () => {
    const [a, b] = [...pointersRef.current.values()];
    if (!a || !b) return null;
    return { dist: Math.hypot(b.x - a.x, b.y - a.y), ang: (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI };
  };

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
      pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointersRef.current.size >= 2) {
        const g = pinchGeom();
        pinchRef.current = g ? { ...g, acc: 0 } : null;
        dragRef.current = null;                       // второй палец — это жест, не осмотр и не выбор
        return;
      }
      dragRef.current = { x: e.clientX, y: e.clientY, moved: 0, id: e.pointerId };
      if (movingSlotId) dragItem(e);
    },
    [movingSlotId, dragItem],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (pointersRef.current.has(e.pointerId)) pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const pinch = pinchRef.current;
      if (pinch && pointersRef.current.size >= 2) {
        const g = pinchGeom();
        if (!g) return;
        viewerRef.current?.zoom((pinch.dist - g.dist) * 1.5);   // пальцы разошлись — ближе
        let turn = g.ang - pinch.ang;
        if (turn > 180) turn -= 360;
        if (turn < -180) turn += 360;
        let acc = pinch.acc + turn;
        if (movingSlotId && Math.abs(acc) >= 15) {
          rotateDraft(acc > 0 ? 15 : -15);
          acc -= acc > 0 ? 15 : -15;
        }
        pinchRef.current = { ...g, acc };
        return;
      }
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
    [movingSlotId, dragItem, rotateDraft],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      pointersRef.current.delete(e.pointerId);
      if (pointersRef.current.size < 2) pinchRef.current = null;
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

  // во «Сверху» ходьбы нет — стрелок нет (их место у нижнего края занимает полоса комнат); на телефоне с открытой панелью
  // выбора — тоже: кадр там в пол-экрана, и стрелки закрывали бы его половину
  const padVisible = ready && !error && padShown && !topView && !props.padSuppressed;
  const toggleVisible = ready && !error && !padShown && !topView && !props.padSuppressed;
  const zones: Zones = {
    top: ZONE_TOP,
    bottom: topView ? ZONE_STRIP : padVisible ? walkPadZone(lite) : toggleVisible ? ZONE_STRIP : ZONE_EDGE,
  };

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
        // колесо: приближение вида сверху; пока предмет «взят» — поворот шагом 15° (flat3d-sims-ux C3)
        onWheel={(e) => (movingSlotId ? rotateDraft(e.deltaY > 0 ? 15 : -15) : viewerRef.current?.zoom(e.deltaY * 0.6))}
        aria-label="3D-вид квартиры"
        role="img"
      />
      {ready && firstLoadDone && !topView && props.spots ? (
        <Hotspots spots={props.spots} project={projectAny} onPick={pickSpot} hidden={Boolean(selectedSlotId || movingSlotId)}
          zones={zones} maxLabels={lite ? 1 : 3} />
      ) : null}
      {ready && selectedSlotId && !movingSlotId && props.onItemOptions && props.itemLabels ? (
        <ObjectTools
          zones={zones}
          project={projectSelected}
          onOptions={props.onItemOptions}
          onMove={props.onItemMove ? () => props.onItemMove!(selectedSlotId) : undefined}
          onRemove={props.onItemRemove ? () => props.onItemRemove!(selectedSlotId) : undefined}
          labels={props.itemLabels}
        />
      ) : null}
      {/* СОСТОЯНИЯ ЭКРАНА (правило ui-rules): загрузка, отказ WebGL с повтором, готово. */}
      {(!ready || progress < 1) && !firstLoadDone ? (
        error ? null : (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-secondary">
            {props.loadingLogo ? (
              // eslint-disable-next-line @next/next/no-img-element -- логотип партнёра: внешний адрес из реестра
              <img src={props.loadingLogo} alt="" style={{ maxHeight: 48, maxWidth: 200, objectFit: "contain" }} />
            ) : null}
            {props.loadingTitle ? <p className="text-lg font-semibold text-primary">{props.loadingTitle}</p> : null}
            {props.loadingHint ? <p className="max-w-xs text-center text-sm text-tertiary">{props.loadingHint}</p> : null}
            <p className="text-sm text-secondary" data-flat3d="loading-stage">
              {props.loadingStages ? props.loadingStages[progress < 0.15 ? 0 : progress < 0.9 ? 1 : 2] : loadingText}
            </p>
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
              onClick={() => rotateDraft(-15)}
            >
              ↺
            </button>
            <button
              type="button"
              aria-label="Повернуть вправо"
              className="min-h-11 min-w-11 rounded-xl bg-secondary text-lg text-primary"
              onClick={() => rotateDraft(15)}
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

      {/* «ПОКАЗАТЬ/СКРЫТЬ УПРАВЛЕНИЕ» (flat3d-sims-ux D4, референс A101): кнопки ходьбы не мешают смотреть, пока не нужны;
          выбор помним в браузере. Ходить можно и без них — стрелками, тапом по полу. «Скрыть» — клеткой в самих стрелках
          (отдельной кнопкой в углу она на узком экране наезжала на них), «Показать» — в углу, когда стрелок нет. */}
      {padVisible ? (
        <WalkPad onHold={holdKey} onTurn={turnBy} compact={lite} liftPx={bottomInsetPx} onHide={togglePad}
          hideLabel={props.padLabels?.hide ?? "Скрыть управление"} />
      ) : null}
      {toggleVisible ? (
        <button type="button" onClick={togglePad} aria-pressed={false}
          className="absolute min-h-11 rounded-lg bg-primary px-3 text-xs text-secondary shadow-md ring-1 ring-inset ring-secondary"
          style={{ left: 8, bottom: 8 + bottomInsetPx, zIndex: 6 }}>
          {props.padLabels?.show ?? "Показать управление"}
        </button>
      ) : null}

      {/* ПОДСКАЗКА — ВВЕРХУ, отдельной карточкой с крестиком (владелец 30.09: «сделай красиво
          вверху, на полупрозрачном фоне, с крестиком, как окно»). Внизу она налезала на кнопки
          ходьбы. Закрыли — больше не показываем: решение помним в браузере. */}
      {!error && ready && !hintClosed && !hintAuto ? (
        <div
          className="pointer-events-auto absolute left-1/2 flex max-w-[92%] -translate-x-1/2 items-start gap-2 rounded-2xl px-4 py-2.5 shadow-sm ring-1 ring-inset ring-secondary"
          // top 60: строка кнопок правой панели (← Вся квартира, ?, i) — сверху, подсказка под ней, не поверх (14.10)
          style={{ top: 60, zIndex: 11, background: "color-mix(in srgb, var(--color-bg-primary) 82%, transparent)", backdropFilter: "blur(8px)" }}
        >
          <p className={`text-xs leading-relaxed text-secondary${props.hintCompact ? " truncate" : ""}`}>{hintText}</p>
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
