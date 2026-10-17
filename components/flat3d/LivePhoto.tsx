"use client";

// «ФОТО» В /flat — ЖИВОЙ СНИМОК ТОЙ ЖЕ СЦЕНЫ (план demo-05 п.8). Раньше режим показывал только текст и кнопки серверного кадра,
// а телефон открывался именно на нём — покупатель при входе не видел комнату вовсе. Теперь — та же сцена движком (`FlatViewer`)
// в позе ракурса окна демо (`apartment.cameras` из `v.cams` витрины, `tools/flat3d/demo-cams.mjs`) с переключателем ракурсов;
// серверный «красивый кадр» остаётся кнопками под снимком (`PhotoView`). Нет WebGL или ракурсов — сразу прежний вид.

import { useEffect, useRef, useState } from "react";

import type { Apartment, CameraPreset } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import type { FlatViewer } from "@/lib/viewer3d/viewer";
import type { Lang } from "@/lib/configurator/i18n";

interface LivePhotoProps {
  apartment: Apartment;
  catalogue: Catalogue;
  scene: ResolvedScene;
  roomId: string;
  lite: boolean;
  lang: Lang;
  /** Снимок не удался (нет WebGL) — показать прежний вид. */
  onFail: () => void;
}

export function LivePhoto({ apartment, catalogue, scene, roomId, lite, lang, onFail }: LivePhotoProps): React.ReactElement | null {
  const cams = apartment.cameras.filter((c) => c.roomId === roomId);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewerRef = useRef<FlatViewer | null>(null);
  const [at, setAt] = useState(0);
  const [loading, setLoading] = useState(true);
  const pose = (c: CameraPreset) => ({ x: c.x, y: c.y, rot: c.rot, fov: c.fov, pose: c.pose, pshift: c.pshift });
  // СНИМОК НЕПОДВИЖЕН — КАДРЫ НЕ КРУТИМ (16.10: постоянный цикл кадров второй сцены на программном рендере CI душил процессор,
  // и e2e падали по таймауту): цикл идёт, пока что-то меняется (загрузка, ракурс, расстановка), и гаснет через 1,5 с
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const kick = (): void => {
    const v = viewerRef.current;
    if (!v) return;
    v.start();
    if (idle.current) clearTimeout(idle.current);
    idle.current = setTimeout(() => viewerRef.current?.stop(), 1500);
  };

  // движок — один на показ режима; расстановка обновляется без пересоздания
  useEffect(() => {
    let cancelled = false;
    const canvas = canvasRef.current;
    if (!canvas || !cams.length) return;
    (async () => {
      try {
        const mod = await import("@/lib/viewer3d/viewer");
        if (cancelled) return;
        const viewer = new mod.FlatViewer(canvas, apartment, catalogue, lite ? mod.LITE_QUALITY : mod.DESKTOP_QUALITY, {
          onProgress: (l, t) => { if (!cancelled && l >= t) setLoading(false); kick(); },
        });
        viewerRef.current = viewer;
        const r = canvas.getBoundingClientRect();
        viewer.setSize(Math.max(320, r.width), Math.max(213, r.height));
        viewer.buildShell(scene);
        viewer.setPhotoPose(pose(cams[0]!));
        kick();
        await viewer.syncObjects(scene);
        if (!cancelled) setLoading(false);
        kick();
      } catch {
        if (!cancelled) onFail();
      }
    })();
    return () => {
      cancelled = true;
      if (idle.current) clearTimeout(idle.current);
      viewerRef.current?.dispose();
      viewerRef.current = null;
    };
    // пересоздаётся только при смене квартиры/качества; сцена и ракурс — ниже
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apartment.id, lite, cams.length]);

  useEffect(() => { kick(); void viewerRef.current?.syncObjects(scene).then(kick); }, [scene]);
  useEffect(() => { const c = cams[at]; if (c) { viewerRef.current?.setPhotoPose(pose(c)); kick(); } }, [at, cams]);

  if (!cams.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {/* на телефоне — во всю ширину и на пол-экрана (критерий п.8: сцена ≥ 50 % экрана), на компьютере — кадр 3:2 */}
      <div className="relative w-full overflow-hidden rounded-xl bg-secondary" style={lite ? { height: "52vh" } : { aspectRatio: "3 / 2" }}>
        <canvas ref={canvasRef} data-flat3d="live-photo" className="block size-full" />
        {loading ? (
          <p className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm text-tertiary">
            {lang === "en" ? "Loading the room…" : "Загружаем комнату…"}
          </p>
        ) : null}
        {cams.length > 1 ? (
          <div className="absolute left-1/2 top-2 flex -translate-x-1/2 gap-1 rounded-full bg-primary p-1 shadow-sm" role="tablist">
            {cams.map((c, i) => (
              <button key={c.id} type="button" role="tab" aria-selected={i === at} onClick={() => setAt(i)}
                className={`min-h-9 rounded-full px-3 text-xs font-medium ${i === at ? "bg-brand-solid text-white" : "text-secondary"}`}>
                {(lang === "en" ? "View " : "Ракурс ") + (i + 1)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
