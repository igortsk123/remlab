"use client";

// Оболочка конфигуратора. Раскладка сделана ПО АНАЛОГИИ с режимом строительства Sims (владелец
// 29.09, со скриншотом игры): сцена занимает весь экран, а выбор живёт ОДНОЙ ПОЛОСОЙ СНИЗУ —
// слева меню (комната и что меняем), справа плитки вариантов. Правой колонки больше нет: она
// отъедала сцену и дублировала то же самое.
//
// Режимы показа: бродилка · сверху · фото · план. Первые два — одна и та же 3D-сцена с разной
// камерой, поэтому переключение мгновенное и ничего не перезагружает.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { formatMoney, t, type Lang } from "@/lib/configurator/i18n";
import { checkPlacement, type Box } from "@/lib/configurator/placement";
import { useFlatConfig } from "@/components/flat3d/useFlatConfig";
import { BuildBar } from "@/components/flat3d/BuildBar";
import { PlanView } from "@/components/flat3d/PlanView";
import { LivePhoto } from "@/components/flat3d/LivePhoto";
import { PhotoView } from "@/components/flat3d/PhotoView";
import { Scene3D } from "@/components/flat3d/Scene3D";
import { InfoPanel } from "@/components/flat3d/InfoPanel";
import { ManagerContact } from "@/components/flat3d/ManagerContact";
import type { Spot } from "@/components/flat3d/Hotspots";
import { optionsForSlot } from "@/lib/configurator/resolve";
import { settle } from "@/lib/configurator/settlement";

type Mode = "walk" | "top" | "photo" | "plan";

interface Props {
  apartment: Apartment;
  catalogue: Catalogue;
  initialConfig?: Configuration | null;
  lang: Lang;
  /** Предельная сумма сертификата застройщика (подсказка, выбор не блокирует), ADR-0254/0258. */
  certificate?: { amount: number } | null;
  /** Факты о квартире строкой (ЖК, срок, этаж) — из карточки застройщика, для правой панели. */
  facts?: string;
  /** Пришёл по ссылке менеджера (`?s=`) — в правой панели «Связаться с менеджером» (E3). */
  sendId?: string | null;
  /** Логотип застройщика для экрана загрузки 3D (D8). */
  logo?: string;
}

export function FlatConfigurator({ apartment, catalogue, initialConfig, lang, certificate, facts, sendId, logo }: Props) {
  const L = t(lang);
  const fmt = (v: number) => formatMoney(v, catalogue.currency, lang);
  const { config, scene, choose, moveSlot, resetSlotPlacement, hideSlot, unhideSlot, reset, undo, redo, canUndo, canRedo, isDefault } = useFlatConfig(
    apartment,
    catalogue,
    initialConfig,
  );
  const [movingSlotId, setMovingSlotId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("plan");
  const [liveOk, setLiveOk] = useState(true);
  const [mobile, setMobile] = useState(false);
  const [barOpen, setBarOpen] = useState(true);
  const [roomId, setRoomId] = useState<string>(
    apartment.rooms.find((r) => r.kind === "living")?.id ?? apartment.rooms[0]!.id,
  );
  const [slotId, setSlotId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [savedUrl, setSavedUrl] = useState<string>("");

  // режим по умолчанию решаем ПОСЛЕ гидрации: сервер не знает ширину экрана
  useEffect(() => {
    const small = window.matchMedia("(max-width: 780px)").matches;
    setMobile(small);
    setMode(small ? "photo" : "walk");
    // на телефоне «Фото» открывается с комнатой на пол-экрана, полоса выбора свёрнута (прогон d8 16.10: сцена занимала 22 %
    // экрана, а полоса закрывала кнопку кадра); откроется касанием предмета или кнопкой
    if (small) setBarOpen(false);
  }, []);

  const room = useMemo(() => apartment.rooms.find((r) => r.id === roomId) ?? apartment.rooms[0]!, [apartment, roomId]);
  const roomTotal = scene.totals.byRoom[room.id] ?? 0;
  const bs = scene.totals.bySettlement;
  const money = settle([{ amount: bs.allowance, settlement: "allowance" }, { amount: bs.developer_surcharge, settlement: "developer_surcharge" },
    { amount: bs.property_price, settlement: "property_price" }], certificate?.amount ?? 0);
  const is3d = mode === "walk" || mode === "top";

  // 3D РАЗВОРАЧИВАЕМ НА ВЕСЬ ЭКРАН (владелец 29.09): по квартире ходят, а не подглядывают в
  // окошко. Просим настоящий полноэкранный режим браузера; если он запрещён (iPhone, политика
  // страницы) — экран всё равно закрывается нашим слоем на всё окно, поведение одинаковое.
  const shellRef = useRef<HTMLDivElement>(null);
  const weWentFullscreen = useRef(false);
  const close3d = useCallback(() => setMode("photo"), []);

  useEffect(() => {
    const el = shellRef.current;
    if (!el) return;
    if (is3d && !document.fullscreenElement) {
      void el
        .requestFullscreen?.()
        .then(() => {
          weWentFullscreen.current = true;
        })
        .catch(() => {
          // запрещено (iPhone, политика страницы) — остаётся наш слой на всё окно
          weWentFullscreen.current = false;
        });
    }
    if (!is3d && document.fullscreenElement) {
      weWentFullscreen.current = false;
      void document.exitFullscreen?.().catch(() => {});
    }
  }, [is3d]);

  // ОТМЕНА С КЛАВИАТУРЫ: Ctrl/⌘+Z — назад, Ctrl/⌘+Shift+Z или Ctrl+Y — вперёд (не в полях ввода)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement | null)?.closest?.("input,textarea,select")) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      else if ((k === "z" && e.shiftKey) || k === "y") { e.preventDefault(); redo(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  const removeItem = useCallback((id: string) => {
    hideSlot(id);
    setSlotId(null);
  }, [hideSlot]);

  useEffect(() => {
    if (!is3d) return;
    // Закрывают 3D крестик и Escape. Выход из ПОЛНОЭКРАННОГО режима сам по себе НЕ закрывает:
    // часть браузеров выходит из него молча и сразу, и человека выбрасывало бы в «Фото» сразу
    // после открытия (ловили на тестах 29.09). Слой на всё окно остаётся — вид не меняется,
    // а первый Escape гасит полноэкранный режим, второй закрывает 3D.
    const onFsChange = () => {
      if (!document.fullscreenElement) weWentFullscreen.current = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.fullscreenElement) close3d();
    };
    document.addEventListener("fullscreenchange", onFsChange);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onFsChange);
      document.removeEventListener("keydown", onKey);
    };
  }, [is3d, close3d]);

  const onPickSlot = useCallback(
    (id: string | null) => {
      setSlotId(id);
      if (!id) return;
      setBarOpen(true);
      const slot = apartment.slots.find((s) => s.id === id);
      if (slot && slot.roomId !== roomId) setRoomId(slot.roomId);
    },
    [apartment.slots, roomId],
  );

  // «Войти в комнату» с плана — ОДНИМ действием: выбрать комнату, включить бродилку и подвести
  // камеру. Раньше клик по плану только менял комнату, и человек оставался на чертеже.
  const enterRoom = useCallback((id: string) => {
    setRoomId(id);
    setSlotId(null);
    setMode("walk");
  }, []);

  // Точки «можно заменить» (D6): мебель текущей комнаты, у которой больше одного варианта; подпись «магазин · название»
  const spots: Spot[] = useMemo(() => scene.items
    .filter((i) => i.roomId === roomId && i.kind === "furniture")
    .filter((i) => {
      const slot = apartment.slots.find((s) => s.id === i.slotId);
      return slot ? optionsForSlot(apartment, catalogue, slot).length > 1 : false;
    })
    .map((i) => {
      const opt = catalogue.options.find((o) => o.id === i.optionId);
      const title = lang === "en" ? i.titleEn : i.titleRu;
      return { slotId: i.slotId, label: opt?.shopName ? `${opt.shopName} · ${title}` : title };
    }), [scene.items, roomId, apartment, catalogue, lang]);

  // Коробки всех предметов сцены — вход для проверки «сюда можно / сюда нельзя».
  const boxes: Box[] = useMemo(
    () =>
      scene.items.map((i) => {
        const slot = apartment.slots.find((s) => s.id === i.slotId);
        return {
          slotId: i.slotId,
          x: i.placement.x,
          y: i.placement.y,
          rot: i.placement.rot,
          wCm: i.placement.wCm,
          dCm: i.placement.dCm,
          role: slot?.photoRole ?? undefined,
          // ваза едет вместе со столиком — помехой при его перемещении быть не может
          flat: (i.placement.elevCm ?? 0) > 40 || (i.asset.kind === "kit" && i.asset.kit === "rug") || !!slot?.tabletop,
        };
      }),
    [scene.items, apartment.slots],
  );

  const canPlace = useCallback(
    (slotId: string, to: { x: number; y: number; rot: number }) => {
      const me = boxes.find((b) => b.slotId === slotId);
      if (!me) return false;
      return checkPlacement({ apartment, boxes, slotId, next: { ...to, wCm: me.wCm, dCm: me.dCm } }).ok;
    },
    [apartment, boxes],
  );

  const startMove = useCallback((slotId: string) => {
    // настольный декор стоит на опоре — его место считает расчёт сцены, вручную не двигается (demo-05 п.9, владелец 08.09)
    if (apartment.slots.find((s) => s.id === slotId)?.tabletop) return;
    setMovingSlotId(slotId);
    setBarOpen(false); // панель выбора мешает целиться в пол
  }, [apartment]);

  const commitMove = useCallback(
    (slotId: string, to: { x: number; y: number; rot: number }) => {
      moveSlot(slotId, to);
      setMovingSlotId(null);
      setBarOpen(true);
    },
    [moveSlot],
  );

  const save = useCallback(async () => {
    setSaveState("saving");
    try {
      const res = await fetch("/api/flat/config", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ configuration: config }),
      });
      const data = (await res.json()) as { id?: string; error?: string };
      if (!res.ok || !data.id) throw new Error(data.error ?? `HTTP ${res.status}`);
      const url = `${window.location.origin}/flat?c=${data.id}`;
      setSavedUrl(url);
      setSaveState("saved");
      try {
        await navigator.clipboard.writeText(url);
      } catch {
        /* буфер недоступен — ссылка показана рядом */
      }
    } catch {
      setSaveState("error");
    }
  }, [config]);

  const modes: { id: Mode; label: string }[] = [
    // облегчённый режим телефона (`lite`) покупателю не подписываем (demo-05 п.8: «Lite» — служебное слово, b2b-12 ставил его
    // для проверки); какой режим включён, видно в `window.__flatViewer.debugState()`
    { id: "walk", label: L.modes.walk },
    { id: "top", label: L.modes.top },
    { id: "photo", label: L.modes.photo },
    { id: "plan", label: L.modes.plan },
  ];

  return (
    <div
      ref={shellRef}
      className="flex flex-col gap-2"
      style={
        is3d
          ? {
              position: "fixed",
              inset: 0,
              zIndex: 60,
              background: "var(--color-bg-primary)",
              padding: 8,
            }
          : undefined
      }
    >
      <header data-flat3d="toolbar" className="flex flex-wrap items-center gap-2">
        <div
          className="flex rounded-lg bg-secondary p-1"
          role="tablist"
          aria-label={lang === "en" ? "View" : "Режим показа"}
        >
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={mode === m.id}
              onClick={() => setMode(m.id)}
              className={`min-h-11 rounded-md px-3 text-sm font-medium ${
                mode === m.id ? "bg-primary text-primary shadow-sm" : "text-secondary"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* на телефоне — без строки комнаты: итог и сертификат важнее, а ширины не хватало (demo-05 п.8) */}
        <span className="hidden text-sm text-tertiary sm:inline">
          {lang === "en" ? room.titleEn : room.titleRu} ·{" "}
          {roomTotal > 0 ? `+${fmt(roomTotal)} ${L.perRoom}` : L.included}
        </span>

        {/* переносится строкой, а не уезжает за край: на телефоне «Сохранить подбор» обрезался правым краем (п.8) */}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          <span className="text-sm text-secondary">
            {L.total}: <b className="text-primary">{fmt(scene.totals.total)}</b>
            {scene.totals.upgrades > 0 ? (
              <span className="hidden text-tertiary sm:inline"> (+{fmt(scene.totals.upgrades)})</span>
            ) : null}
          </span>
          {/* на телефоне сертификат уже в строке застройщика — строку «выбрано» не повторяем, итоги в одну строку (п.8) */}
          {/* ДЕНЬГИ — ОБЩИМ ЯДРОМ (demo-06): в сертификат — только мебель и встроенное; отделка застройщика (пол) — своей строкой:
              RF — доплата застройщику, UK — к цене квартиры. Раньше пол съел бы сертификат */}
          {certificate && !mobile ? <CertificateLine amount={certificate.amount} spent={money.allowanceEligible} fmt={fmt} lang={lang} /> : null}
          {money.developerSurcharge > 0 ? <span className="text-sm text-tertiary">{L.devSurcharge} <b className="text-primary">+{fmt(money.developerSurcharge)}</b></span> : null}
          {money.propertyPriceDelta > 0 ? <span className="text-sm text-tertiary">{L.propertyDelta} <b className="text-primary">+{fmt(money.propertyPriceDelta)}</b></span> : null}
          {/* кнопки — одной группой: при переносе строки «отменить/вернуть» не разъезжаются по разным строкам (п.8) */}
          <div className="flex items-center gap-2">
          <UndoRedo lang={lang} undo={undo} redo={redo} canUndo={canUndo} canRedo={canRedo} />
          {!isDefault ? (
            <button
              type="button"
              onClick={reset}
              className="min-h-11 rounded-lg px-3 text-sm text-secondary ring-1 ring-inset ring-secondary"
            >
              {lang === "en" ? "Reset" : "Сброс"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void save()}
            disabled={saveState === "saving"}
            className="min-h-11 rounded-lg bg-brand-solid px-4 text-sm font-semibold text-white disabled:opacity-60"
          >
            {saveState === "saving" ? L.saving : mobile ? (lang === "en" ? "Save" : "Сохранить") : L.save}
          </button>
          {is3d ? (
            <button
              type="button"
              onClick={close3d}
              aria-label={lang === "en" ? "Close 3D" : "Закрыть 3D"}
              className="min-h-11 min-w-11 rounded-lg text-lg text-secondary ring-1 ring-inset ring-secondary"
            >
              ✕
            </button>
          ) : null}
          </div>
        </div>
      </header>

      {saveState === "saved" ? (
        <p className="truncate text-xs text-secondary">
          {L.saved}:{" "}
          <a className="underline" href={savedUrl}>
            {savedUrl}
          </a>
        </p>
      ) : null}
      {saveState === "error" ? (
        <p className="text-xs text-error-primary">
          {lang === "en" ? "Could not save, try again" : "Не удалось сохранить, попробуйте ещё раз"}
        </p>
      ) : null}

      {/* Сцена и панель — ДРУГ ПОД ДРУГОМ, панель не накрывает сцену: иначе предметы в нижней
          части кадра нельзя ни разглядеть, ни выбрать (поймано тестом 29.09). */}
      <section
        aria-label={lang === "en" ? "Apartment view" : "Вид квартиры"}
        className="flex w-full flex-col gap-2"
        // В полноэкранном 3D сцена забирает всё, что осталось от строки режимов и панели выбора;
        // в обычном показе (фото, план) высота считается от окна: 250 px — шапка сайта, заголовок
        // и строка режимов (замерено 29.09).
        style={
          is3d
            ? { flex: "1 1 auto", minHeight: 0 }
            // в «Фото» на телефоне — по содержимому: снимок + кнопки кадра не влезали в 70vh и уходили под кнопку полосы (п.8)
            : mobile && mode === "photo" ? { minHeight: 460 } : { height: mobile ? "70vh" : "calc(100vh - 250px)", minHeight: 460 }
        }
      >
        {/* min-height: 0 обязателен, иначе канвас не даёт колонке сжаться и панель уезжает
            за экран; задаём стилем — утилита `min-h-0` в собранном CSS отсутствует */}
        <div className="relative" style={{ flex: "1 1 auto", minHeight: 0 }}>
        {is3d ? (
          <Scene3D
            apartment={apartment}
            catalogue={catalogue}
            scene={scene}
            lite={mobile}
            topView={mode === "top"}
            roomId={roomId}
            selectedSlotId={slotId}
            onPickSlot={onPickSlot}
            movingSlotId={movingSlotId}
            canPlace={canPlace}
            onMoveCommit={commitMove}
            onMoveCancel={() => {
              setMovingSlotId(null);
              setBarOpen(true);
            }}
            onRoomChange={(id) => id && setRoomId(id)}
            onItemOptions={() => setBarOpen(true)}
            spots={spots}
            padLabels={lang === "en" ? { show: "Show controls", hide: "Hide controls" } : { show: "Показать управление", hide: "Скрыть управление" }}
            onItemMove={slotId && apartment.slots.find((s) => s.id === slotId)?.tabletop ? undefined : startMove}
            onItemRemove={slotId && apartment.slots.find((s) => s.id === slotId)?.kind === "furniture" ? removeItem : undefined}
            itemLabels={lang === "en" ? { options: "Options", move: "Drag", remove: "Remove" } : { options: "Варианты", move: "Двигать", remove: "Убрать" }}   // не «Передвинуть»: та кнопка есть в нижней панели
            hintText={mobile ? L.walkHintMobile : L.walkHint}
            hintCompact={mobile}
            loadingText={L.loading}
            loadingTitle={L.loadingTitle}
            loadingHint={L.loadingHint}
            loadingStages={L.loadingStages}
            loadingLogo={logo}
            noWebglText={L.noWebgl}
            retryText={lang === "en" ? "Try again" : "Повторить"}
          />
        ) : null}
        {is3d ? (
          <InfoPanel apartment={apartment} scene={scene} roomId={roomId} facts={facts ?? ""} lang={lang} fmt={fmt}
            inRoom={mode === "walk"} onRoom={(id) => setRoomId(id)} onOverview={() => setMode("top")} defaultOpen={false}
            hidden={config.hidden ?? []} onUnhide={unhideSlot}
            contact={sendId ? <ManagerContact sendId={sendId} lang={lang} sum={scene.totals.upgrades}
              items={scene.items.filter((i) => i.price > 0).map((i) => (lang === "en" ? i.titleEn : i.titleRu))} /> : null} />
        ) : null}
        {mode === "top" ? (
          // КНОПКИ КОМНАТ НА ВИДЕ СВЕРХУ (flat3d-sims-ux D3): войти в комнату одним нажатием, как на плане
          <div data-flat3d="rooms-top" style={{ position: "absolute", left: 8, bottom: 8, zIndex: 4, display: "flex", flexWrap: "wrap", gap: 6, maxWidth: "70%" }}>
            {apartment.rooms.map((r) => (
              <button key={r.id} type="button" onClick={() => enterRoom(r.id)}
                className="min-h-11 rounded-lg bg-primary px-3 text-sm text-secondary shadow-md ring-1 ring-inset ring-secondary">
                {(lang === "en" ? "Enter: " : "Войти: ") + (lang === "en" ? r.titleEn : r.titleRu)}
              </button>
            ))}
          </div>
        ) : null}
        {is3d ? null : mode === "photo" ? (
          <div className="flex h-full flex-col gap-3 overflow-auto">
            {/* живой снимок той же сцены в ракурсе окна (demo-05 п.8); нет ракурсов или WebGL — только прежний вид */}
            {liveOk ? <LivePhoto apartment={apartment} catalogue={catalogue} scene={scene} roomId={room.id} lite={mobile} lang={lang}
              onFail={() => setLiveOk(false)} /> : null}
            <PhotoView apartment={apartment} scene={scene} roomId={room.id} lang={lang} />
          </div>
        ) : (
          <PlanView
            apartment={apartment}
            scene={scene}
            activeRoomId={roomId}
            selectedSlotId={slotId}
            onRoom={(id) => setRoomId(id)}
            onEnterRoom={enterRoom}
            onSlot={onPickSlot}
            lang={lang}
          />
        )}
        </div>

        {barOpen ? (
          <BuildBar
            apartment={apartment}
            catalogue={catalogue}
            roomId={roomId}
            slotId={slotId}
            selections={scene.selections}
            lang={lang}
            onRoom={(id) => {
              setRoomId(id);
              setSlotId(null);
            }}
            onSlot={setSlotId}
            onChoose={choose}
            onMove={is3d ? startMove : undefined}
            onResetPlacement={
              slotId && config.placements?.[slotId] ? () => resetSlotPlacement(slotId) : undefined
            }
            onClose={() => setBarOpen(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setBarOpen(true)}
            className="min-h-11 self-center rounded-lg bg-brand-solid px-4 text-sm font-semibold text-white"
          >
            {lang === "en" ? "Choose finishes" : "Выбрать отделку и мебель"}
          </button>
        )}
      </section>
    </div>
  );
}

/** «↶ ↷» — отмена и возврат любого действия покупателя (flat3d-sims-ux, критерии приёмки). */
function UndoRedo({ lang, undo, redo, canUndo, canRedo }: { lang: Lang; undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean }) {
  const cls = "min-h-11 min-w-11 rounded-lg text-lg text-secondary ring-1 ring-inset ring-secondary disabled:opacity-40";
  return (
    <>
      <button type="button" className={cls} onClick={undo} disabled={!canUndo} aria-label={lang === "en" ? "Undo" : "Отменить"} title={lang === "en" ? "Undo (Ctrl+Z)" : "Отменить (Ctrl+Z)"}>↶</button>
      <button type="button" className={cls} onClick={redo} disabled={!canRedo} aria-label={lang === "en" ? "Redo" : "Вернуть"} title={lang === "en" ? "Redo" : "Вернуть"}>↷</button>
    </>
  );
}

/** «Сертификат до X · выбрано на Y · доплата Z» — подсказка, выбор не блокирует (ADR-0254 п.2). */
function CertificateLine({ amount, spent, fmt, lang }: { amount: number; spent: number; fmt: (v: number) => string; lang: Lang }) {
  const extra = Math.max(0, spent - amount);
  return (
    <span className="text-sm text-tertiary">
      {lang === "en" ? "Allowance" : "Сертификат"} {fmt(amount)} · {lang === "en" ? "chosen" : "выбрано"} {fmt(spent)}
      {extra > 0 ? <> · {lang === "en" ? "top-up" : "доплата"} <b className="text-primary">{fmt(extra)}</b></> : null}
    </span>
  );
}
