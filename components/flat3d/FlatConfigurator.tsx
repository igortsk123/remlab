"use client";

// Оболочка конфигуратора: три режима показа поверх ОДНОГО состояния выбора.
// Desktop открывается в 3D, телефон — в «Фото» с кнопкой «3D Lite» (требование ТЗ: на телефоне
// тяжёлая сцена не должна встречать человека первой).

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { formatGbp, t, type Lang } from "@/lib/configurator/i18n";
import { useFlatConfig } from "@/components/flat3d/useFlatConfig";
import { OptionPicker } from "@/components/flat3d/OptionPicker";
import { PlanView } from "@/components/flat3d/PlanView";
import { PhotoView } from "@/components/flat3d/PhotoView";
import { Scene3D } from "@/components/flat3d/Scene3D";

type Mode = "3d" | "photo" | "plan";

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
  const [lite, setLite] = useState(false);
  const [roomId, setRoomId] = useState<string>(apartment.rooms.find((r) => r.kind === "living")?.id ?? apartment.rooms[0]!.id);
  const [slotId, setSlotId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [savedUrl, setSavedUrl] = useState<string>("");

  // режим по умолчанию решаем ПОСЛЕ гидрации: сервер не знает ширину экрана
  useEffect(() => {
    const small = window.matchMedia("(max-width: 780px)").matches;
    setMobile(small);
    setMode(small ? "photo" : "3d");
  }, []);

  const room = useMemo(() => apartment.rooms.find((r) => r.id === roomId) ?? apartment.rooms[0]!, [apartment, roomId]);
  const roomTotal = scene.totals.byRoomGbp[room.id] ?? 0;

  const onPickSlot = useCallback(
    (id: string | null) => {
      setSlotId(id);
      if (!id) return;
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
        /* буфер недоступен — ссылка всё равно показана рядом */
      }
    } catch {
      setSaveState("error");
    }
  }, [config]);

  return (
    <div className="flex min-h-[80vh] flex-col gap-3 lg:h-[calc(100vh-140px)] lg:flex-row">
      {/* min-w-0 обязателен: без него длинные названия в правой колонке раздувают её
          и сжимают сцену до узкой полоски (поймано кадром 28.09) */}
      <section className="flex min-h-[46vh] min-w-0 flex-1 flex-col gap-2 lg:min-h-0">
        <header className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg bg-secondary p-1" role="tablist" aria-label={lang === "en" ? "View" : "Режим показа"}>
            {(["3d", "photo", "plan"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`min-h-11 rounded-md px-4 text-sm font-medium ${
                  mode === m ? "bg-primary text-primary shadow-sm" : "text-secondary"
                }`}
              >
                {m === "3d" ? L.modes.d3 : m === "photo" ? L.modes.photo : L.modes.plan}
              </button>
            ))}
          </div>
          {mobile && mode === "3d" ? (
            <span className="rounded-full bg-secondary px-3 py-1 text-xs text-secondary">3D Lite</span>
          ) : null}
          <span className="ml-auto text-sm text-tertiary">
            {lang === "en" ? room.titleEn : room.titleRu} ·{" "}
            {roomTotal > 0 ? `+${formatGbp(roomTotal, lang)} ${L.perRoom}` : L.included}
          </span>
        </header>

        <div className="h-[56vh] min-w-0 flex-1 lg:h-auto">
          {mode === "3d" ? (
            <Scene3D
              apartment={apartment}
              catalogue={catalogue}
              scene={scene}
              lite={mobile || lite}
              roomId={roomId}
              onPickSlot={onPickSlot}
              onRoomChange={(id) => id && setRoomId(id)}
              hintText={mobile ? L.walkHintMobile : L.walkHint}
              loadingText={L.loading}
              noWebglText={L.noWebgl}
              retryText={lang === "en" ? "Try again" : "Повторить"}
            />
          ) : mode === "photo" ? (
            <div className="flex h-full flex-col gap-2">
              <PhotoView apartment={apartment} scene={scene} roomId={roomId} lang={lang} />
              {mobile ? (
                <button
                  type="button"
                  onClick={() => {
                    setLite(true);
                    setMode("3d");
                  }}
                  className="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary ring-1 ring-inset ring-secondary"
                >
                  {L.liteOn}
                </button>
              ) : null}
            </div>
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
      </section>

      <aside className="flex w-full flex-col gap-3 lg:w-[400px]">
        <nav aria-label={L.rooms} className="flex flex-wrap gap-1.5">
          {apartment.rooms.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => {
                setRoomId(r.id);
                setSlotId(null);
              }}
              className={`min-h-11 rounded-lg px-3 text-sm font-medium ${
                r.id === roomId ? "bg-brand-solid text-white" : "bg-secondary text-secondary"
              }`}
            >
              {lang === "en" ? r.titleEn : r.titleRu}
            </button>
          ))}
        </nav>

        <div className="min-h-[38vh] flex-1 overflow-hidden rounded-xl bg-secondary p-3 lg:min-h-0">
          <OptionPicker
            apartment={apartment}
            catalogue={catalogue}
            roomId={roomId}
            selections={scene.selections}
            selectedSlotId={slotId}
            onSelectSlot={setSlotId}
            onChoose={choose}
            lang={lang}
          />
        </div>

        <section aria-label="Стоимость" className="rounded-xl bg-primary p-3 ring-1 ring-inset ring-secondary">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-tertiary">{L.base}</span>
            <span className="text-secondary">{formatGbp(scene.totals.basePriceGbp, lang)}</span>
          </div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-tertiary">
              {L.upgrades} · {scene.totals.upgradeCount}
            </span>
            <span className="text-secondary">+{formatGbp(scene.totals.upgradesGbp, lang)}</span>
          </div>
          <div className="mt-1 flex items-baseline justify-between border-t border-secondary pt-2 text-base font-semibold">
            <span>{L.total}</span>
            <span>{formatGbp(scene.totals.totalGbp, lang)}</span>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void save()}
              disabled={saveState === "saving"}
              className="min-h-11 flex-1 rounded-lg bg-brand-solid px-4 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saveState === "saving" ? L.saving : L.save}
            </button>
            {!isDefault ? (
              <button
                type="button"
                onClick={reset}
                className="min-h-11 rounded-lg px-3 text-sm text-secondary ring-1 ring-inset ring-secondary"
              >
                {lang === "en" ? "Reset" : "Сброс"}
              </button>
            ) : null}
          </div>
          {saveState === "saved" ? (
            <p className="mt-2 break-all text-xs text-secondary">
              {L.saved}: <a className="underline" href={savedUrl}>{savedUrl}</a>
            </p>
          ) : null}
          {saveState === "error" ? (
            <p className="mt-2 text-xs text-error-primary">
              {lang === "en" ? "Could not save, try again" : "Не удалось сохранить, попробуйте ещё раз"}
            </p>
          ) : null}
        </section>
      </aside>
    </div>
  );
}
