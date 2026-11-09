"use client";

// Серый 3D-тур результата пробы (план agent-trial-01, T-C): листы (этажи) вкладками, вид «3D» / «сверху», список комнат
// (касание → камера к комнате), комнаты с флагами — штриховка и «?». Плашки: автоматическое прочтение плана всегда;
// масштаб не подтверждён — `Scale not verified`. Сцена — `lib/trial/grey-scene.ts`, рантайм — `useGreyViewer.ts`.

import { useRef, useState } from "react";
import type { FloorplanResult } from "@/contracts/trial";
import type { TrialPanel, TrialRoom } from "@/lib/trial/grey-scene";
import { useGreyViewer, type ViewMode } from "@/components/trial/useGreyViewer";
import s from "@/components/trial/trial.module.css";

export const AUTO_NOTE = "Automatically interpreted floor plan — verify flagged dimensions before marketing use.";

const FLAG_TEXT: Record<string, string> = {
  size_unconfirmed: "size not confirmed",
  merged_rooms: "may be two rooms",
  scale_unverified: "scale not verified",
};
const flagText = (r: TrialRoom) => FLAG_TEXT[r.flags[0] ?? ""] ?? "check this room";
const metres = (cm: number) => (cm / 100).toFixed(2).replace(/0$/, "");

export function GreyTour({ result }: { result: FloorplanResult }) {
  const [pi, setPi] = useState(0);
  const panel = result.panels[pi] ?? result.panels[0]!;
  return (
    <div className="stack" style={{ gap: 12 }}>
      {result.panels.length > 1 ? (
        <div className={s.tabs} role="tablist" aria-label="Floors">
          {result.panels.map((p, i) => (
            <button key={p.id} type="button" role="tab" aria-selected={i === pi} className={s.pill} onClick={() => setPi(i)}>
              {p.title || `Floor ${i + 1}`}
            </button>
          ))}
        </div>
      ) : null}
      <PanelTour key={panel.id} panel={panel} scaleOk={result.scale.status !== "not_verified"} />
    </div>
  );
}

function PanelTour({ panel, scaleOk }: { panel: TrialPanel; scaleOk: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("oblique");
  const viewer = useGreyViewer(box, layer, panel, selected);
  const go = (next: ViewMode) => { setMode(next); setSelected(null); viewer.flyTo(next); };
  const pick = (id: string) => {
    if (id === selected) { go(mode); return; }
    setSelected(id);
    viewer.flyTo({ room: id });
  };
  return (
    <div className={s.tour}>
      <div className={s.stage}>
        <div ref={box} data-testid="grey-tour" data-rooms={panel.rooms.length} className={s.canvas}>
          <div ref={layer} className={s.labels} aria-hidden="true">
            {panel.rooms.map((r) => (
              <span key={r.id} data-room={r.id} data-flagged={r.flags.length ? "1" : "0"} className={s.roomLabel}>
                <b>{r.name}</b>{r.flags.length ? <i className={s.q}>?</i> : null}
              </span>
            ))}
          </div>
          {viewer.status === "loading" ? <p className={`${s.msg} muted`}>Loading 3D…</p> : null}
          {viewer.status === "no-webgl" ? (
            <p className={`${s.msg} muted`}>This browser can&apos;t show 3D. The room list still works.</p>
          ) : null}
          <div className={s.tools}>
            <button type="button" className={s.pill} aria-pressed={mode === "oblique" && !selected} onClick={() => go("oblique")}>3D</button>
            <button type="button" className={s.pill} aria-pressed={mode === "top" && !selected} onClick={() => go("top")}>From above</button>
          </div>
        </div>
        <div className={s.notes}>
          {!scaleOk ? <p className={s.warn}><b>Scale not verified.</b> Room sizes may be off.</p> : null}
          <p>{AUTO_NOTE}</p>
        </div>
      </div>
      <div className={s.rooms}>
        <p className={`${s.hint} muted`}>Tap a room to look at it.</p>
        <ul className={s.roomList} aria-label="Rooms">
          {panel.rooms.map((r) => (
            <li key={r.id}>
              <button type="button" className={s.room} aria-pressed={selected === r.id} onClick={() => pick(r.id)}>
                <span className={s.roomName}>{r.name}{r.flags.length ? <i className={s.q} aria-label="needs checking">?</i> : null}</span>
                <span className={s.roomMeta}>
                  {r.areaM2 > 0 ? `${r.areaM2.toFixed(1)} m²` : "size unknown"}
                  {r.dims ? ` · ${metres(r.dims.w)} × ${metres(r.dims.d)} m` : ""}
                  {r.flags.length ? <em> · {flagText(r)}</em> : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
