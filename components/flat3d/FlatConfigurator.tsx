"use client";

// Оболочка конфигуратора. Раскладка сделана ПО АНАЛОГИИ с режимом строительства Sims (владелец
// 29.09, со скриншотом игры): сцена занимает весь экран, а выбор живёт ОДНОЙ ПОЛОСОЙ СНИЗУ —
// слева меню (комната и что меняем), справа плитки вариантов. Правой колонки больше нет: она
// отъедала сцену и дублировала то же самое.
//
// Режимы показа: бродилка · сверху · фото · план. Первые два — одна и та же 3D-сцена с разной
// камерой, поэтому переключение мгновенное и ничего не перезагружает.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { formatGbp, t, type Lang } from "@/lib/configurator/i18n";
import { useFlatConfig } from "@/components/flat3d/useFlatConfig";
import { BuildBar } from "@/components/flat3d/BuildBar";
import { PlanView } from "@/components/flat3d/PlanView";
import { PhotoView } from "@/components/flat3d/PhotoView";
import { Scene3D } from "@/components/flat3d/Scene3D";

type Mode = "walk" | "top" | "photo" | "plan";

interface Props {
  apartment: Apartment;
  catalogue: Catalogue;
  initialConfig?: Configuration | null;
  lang: Lang;
}

export function FlatConfigurator({ apartment, catalogue, initialConfig, lang }: Props) {
  const L = t(lang);
  const { config, scene, choose, reset, isDefault } = useFlatConfig(apartment, catalogue, initialConfig);
  const [mode, setMode] = useState<Mode>("plan");
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
  }, []);

  const room = useMemo(() => apartment.rooms.find((r) => r.id === roomId) ?? apartment.rooms[0]!, [apartment, roomId]);
  const roomTotal = scene.totals.byRoomGbp[room.id] ?? 0;
  const is3d = mode === "walk" || mode === "top";

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
    { id: "walk", label: L.modes.walk },
    { id: "top", label: L.modes.top },
    { id: "photo", label: L.modes.photo },
    { id: "plan", label: L.modes.plan },
  ];

  return (
    <div className="flex flex-col gap-2">
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

        <span className="text-sm text-tertiary">
          {lang === "en" ? room.titleEn : room.titleRu} ·{" "}
          {roomTotal > 0 ? `+${formatGbp(roomTotal, lang)} ${L.perRoom}` : L.included}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-sm text-secondary">
            {L.total}: <b className="text-primary">{formatGbp(scene.totals.totalGbp, lang)}</b>
            {scene.totals.upgradesGbp > 0 ? (
              <span className="text-tertiary"> (+{formatGbp(scene.totals.upgradesGbp, lang)})</span>
            ) : null}
          </span>
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
            {saveState === "saving" ? L.saving : L.save}
          </button>
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
        // высота подобрана так, чтобы панель выбора помещалась на экране без прокрутки страницы
        style={{ height: mobile ? "70vh" : "calc(100vh - 290px)", minHeight: 460 }}
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
            onRoomChange={(id) => id && setRoomId(id)}
            hintText={mobile ? L.walkHintMobile : L.walkHint}
            loadingText={L.loading}
            noWebglText={L.noWebgl}
            retryText={lang === "en" ? "Try again" : "Повторить"}
          />
        ) : mode === "photo" ? (
          <PhotoView apartment={apartment} scene={scene} roomId={room.id} lang={lang} />
        ) : (
          <PlanView
            apartment={apartment}
            scene={scene}
            activeRoomId={roomId}
            selectedSlotId={slotId}
            onRoom={(id) => setRoomId(id)}
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
