"use client";

import { useState } from "react";
import type { Apartment } from "@/contracts/apartment";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import type { Lang } from "@/lib/configurator/i18n";

// ПРАВАЯ ПАНЕЛЬ СОСТАВА (план flat3d-sims-ux E1/E2/E3/D5/D7): факты о квартире, комнаты с суммой, предметы текущей
// комнаты с ценой, итог; сворачивается «✕», возвращается кнопкой «i». «← Вся квартира» — из комнаты на вид
// сверху; «?» — короткая справка по управлению. Только в 3D: на плане и фото состав уже виден.
type Props = {
  apartment: Apartment;
  scene: ResolvedScene;
  roomId: string;
  facts: string;
  lang: Lang;
  fmt: (v: number) => string;
  inRoom: boolean;
  onRoom: (id: string) => void;
  onOverview: () => void;
  defaultOpen: boolean;
  /** Убранные покупателем предметы — строкой «вернуть» (flat3d-sims-ux «убрать»). */
  hidden: string[];
  onUnhide: (slotId: string) => void;
  /** Кнопка связи с менеджером застройщика (только по его ссылке) — под итогом. */
  contact?: React.ReactNode;
};

const HELP: Record<Lang, string[]> = {
  ru: ["Ходите кнопками внизу или стрелками, смотрите — перетаскиванием.", "Нажмите на предмет — над ним появятся «Варианты», «Двигать» и «Убрать».",
    "Перемещение: тяните предмет, зелёный — встанет, красный — нет; ↺ ↻ поворачивают.", "↶ отменяет последнее действие, ↷ возвращает (Ctrl+Z).",
    "«Сохранить» даёт ссылку на ваш подбор."],
  en: ["Walk with the buttons below or the arrow keys, drag to look around.", "Tap an item — “Options”, “Drag” and “Remove” appear above it.",
    "Moving: drag the item, green fits, red does not; ↺ ↻ rotate it.", "↶ undoes the last action, ↷ redoes it (Ctrl+Z).",
    "“Save” gives you a link to your selection."],
};

/** Ролики к строкам справки: ходьба, выбор предмета, перемещение (порядок строк HELP). */
const CLIPS: (string | null)[] = ["walk", "pick", "move", null, null];

export function InfoPanel(p: Props) {
  const [open, setOpen] = useState(p.defaultOpen);
  const [help, setHelp] = useState(false);
  const en = p.lang === "en";
  const items = p.scene.items.filter((i) => i.roomId === p.roomId && i.kind === "furniture");
  const btn = "min-h-11 min-w-11 rounded-lg bg-primary px-3 text-sm text-secondary ring-1 ring-inset ring-secondary";

  return (
    <div data-flat3d="info" style={{ position: "absolute", top: 8, right: 8, zIndex: 12, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, maxWidth: "min(340px, 92vw)" }}>
      <div className="flex gap-2">
        {p.inRoom ? <button type="button" className={btn} onClick={p.onOverview}>{en ? "← Whole flat" : "← Вся квартира"}</button> : null}
        <button type="button" className={btn} aria-label={en ? "Help" : "Справка"} onClick={() => setHelp((h) => !h)}>?</button>
        {!open ? <button type="button" className={btn} onClick={() => setOpen(true)}>{en ? "i · Details" : "i · Состав и цены"}</button> : null}
      </div>
      {help ? (
        <div className="rounded-lg bg-primary p-3 text-sm text-secondary shadow-md">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{HELP[p.lang].map((h, i) => (
            <li key={h}>{h}{CLIPS[i] ? (
              // короткий ролик приёма (D5): анимированный WebP, снят `tools/flat3d/help-clips.mjs`
              // eslint-disable-next-line @next/next/no-img-element -- анимированный WebP: next/image его не анимирует
              <img src={`/flat3d-help/${CLIPS[i]}.webp`} alt="" loading="lazy"
                style={{ display: "block", width: "100%", borderRadius: 6, margin: "4px 0 8px" }} />
            ) : null}</li>
          ))}</ul>
        </div>
      ) : null}
      {open ? (
        <aside className="rounded-xl bg-primary p-3 text-sm shadow-md" style={{ width: "100%", maxHeight: "60vh", overflowY: "auto" }}>
          <div className="flex items-start justify-between gap-2">
            <b className="text-primary">{en ? p.apartment.titleEn : p.apartment.titleRu}</b>
            <button type="button" className="min-h-8 min-w-8 text-secondary" aria-label={en ? "Close" : "Закрыть"} onClick={() => setOpen(false)}>✕</button>
          </div>
          {p.facts ? <p className="text-tertiary" style={{ margin: "2px 0 8px" }}>{p.facts}</p> : null}
          <div className="text-tertiary">{en ? "Rooms" : "Комнаты"}</div>
          {p.apartment.rooms.map((r) => (
            <button key={r.id} type="button" onClick={() => p.onRoom(r.id)} className="flex w-full justify-between py-1 text-left"
              style={{ fontWeight: r.id === p.roomId ? 600 : 400 }}>
              <span>{en ? r.titleEn : r.titleRu}</span>
              <span className="text-tertiary">{(p.scene.totals.byRoom[r.id] ?? 0) > 0 ? `+${p.fmt(p.scene.totals.byRoom[r.id]!)}` : en ? "included" : "входит"}</span>
            </button>
          ))}
          {items.length ? <div className="mt-2 text-tertiary">{en ? "In this room" : "В этой комнате"}</div> : null}
          {items.map((i) => (
            <div key={i.slotId} className="flex justify-between gap-2 py-1">
              <span className="truncate">{en ? i.titleEn : i.titleRu}</span>
              <span className="shrink-0 text-tertiary">{i.price > 0 ? `+${p.fmt(i.price)}` : en ? "incl." : "вх."}</span>
            </div>
          ))}
          {p.hidden.filter((id) => p.apartment.slots.find((s) => s.id === id)?.roomId === p.roomId).map((id) => {
            const slot = p.apartment.slots.find((s) => s.id === id)!;
            return (
              <div key={id} className="flex justify-between gap-2 py-1 text-tertiary">
                <span className="truncate">{(en ? slot.titleEn : slot.titleRu) + (en ? " — removed" : " — убрано")}</span>
                <button type="button" className="shrink-0 underline" onClick={() => p.onUnhide(id)}>{en ? "Bring back" : "Вернуть"}</button>
              </div>
            );
          })}
          <div className="mt-2 flex justify-between border-t border-secondary pt-2">
            <b>{en ? "Total" : "Итого"}</b><b>{p.fmt(p.scene.totals.total)}</b>
          </div>
          {p.contact}
        </aside>
      ) : null}
    </div>
  );
}
