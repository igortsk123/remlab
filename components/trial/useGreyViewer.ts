"use client";

// Рантайм серого тура (план agent-trial-01, T-C): WebGL, вращение/зум (OrbitControls), перелёт камеры, подписи комнат
// поверх холста. Рисует по требованию (после движения камеры), а не каждый кадр — телефону и CI без видеокарты легче.

import { useEffect, useRef, useState, type RefObject } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { buildGreyScene, fitView, roomView, type GreyScene, type TrialPanel, type View } from "@/lib/trial/grey-scene";

export type ViewMode = "oblique" | "top";
export type Viewer = { status: "loading" | "ready" | "no-webgl"; flyTo(mode: ViewMode | { room: string }): void };

const TWEEN_MS = 450;

function hatchTexture(): THREE.Texture | null {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  if (!g) return null;
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, 64, 64);
  g.strokeStyle = "#a8a29e";
  g.lineWidth = 7;
  for (const k of [-1, 0, 1]) { g.beginPath(); g.moveTo(k * 64, 64); g.lineTo(k * 64 + 64, 0); g.stroke(); }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(2.5, 2.5); // шаг штриховки ~40 см
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Подписи: проекция точки комнаты на экран; маленькая на экране комната — только «?» (у флажков) без названия. */
function placeLabels(gs: GreyScene, cam: THREE.Camera, box: HTMLElement, layer: HTMLElement, selected: string | null) {
  const w = box.clientWidth, h = box.clientHeight;
  const v = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3();
  for (const r of gs.rooms) {
    const el = layer.querySelector<HTMLElement>(`[data-room="${CSS.escape(r.id)}"]`);
    if (!el) continue;
    v.copy(r.label).project(cam);
    a.set(r.center.x - r.size.x / 2, 0, r.center.z).project(cam);
    b.set(r.center.x + r.size.x / 2, 0, r.center.z).project(cam);
    const span = Math.hypot((a.x - b.x) * w, (a.y - b.y) * h) / 2;
    const visible = v.z < 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1;
    el.style.display = visible ? "" : "none";
    el.dataset.compact = span < 64 && r.id !== selected ? "1" : "0";
    el.style.transform = `translate(-50%, -50%) translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px)`;
  }
}

export function useGreyViewer(
  box: RefObject<HTMLDivElement | null>, layer: RefObject<HTMLDivElement | null>, panel: TrialPanel, selected: string | null,
): Viewer {
  const [status, setStatus] = useState<Viewer["status"]>("loading");
  const api = useRef<{ fly(v: View): void; gs: GreyScene; aspect(): number; redraw(): void } | null>(null);
  const sel = useRef(selected);

  useEffect(() => {
    const el = box.current, lab = layer.current;
    if (!el || !lab) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch {
      setStatus("no-webgl");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.setAttribute("aria-label", "3D model of the floor plan");
    renderer.domElement.style.display = "block";
    el.prepend(renderer.domElement);
    const hatch = hatchTexture();
    const gs = buildGreyScene(panel, { hatch, transparent: true });
    const cam = new THREE.PerspectiveCamera(35, 1, 0.05, 400);
    const controls = new OrbitControls(cam, renderer.domElement);
    controls.maxPolarAngle = Math.PI / 2 - 0.05;
    controls.minDistance = 1.5;
    controls.screenSpacePanning = true;
    let raf = 0;
    const draw = () => {
      renderer.render(gs.scene, cam);
      placeLabels(gs, cam, el, lab, sel.current);
    };
    const aspect = () => Math.max(el.clientWidth, 1) / Math.max(el.clientHeight, 1);
    const resize = () => {
      renderer.setSize(el.clientWidth, el.clientHeight, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      cam.aspect = aspect();
      cam.updateProjectionMatrix();
      draw();
    };
    const fly = (to: View) => {
      cancelAnimationFrame(raf);
      const p0 = cam.position.clone(), t0 = controls.target.clone(), start = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - start) / TWEEN_MS), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
        cam.position.lerpVectors(p0, to.position, e);
        controls.target.lerpVectors(t0, to.target, e);
        controls.update();
        draw();
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    const first = fitView(gs.center, gs.size.x, gs.size.z, aspect(), "oblique");
    cam.position.copy(first.position);
    controls.target.copy(first.target);
    controls.maxDistance = first.position.distanceTo(first.target) * 4;
    controls.update();
    controls.addEventListener("change", draw);
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    api.current = { fly, gs, aspect, redraw: draw };
    el.dataset.ready = "1";
    setStatus("ready");
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      gs.dispose();
      hatch?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      api.current = null;
      delete el.dataset.ready;
    };
  }, [box, layer, panel]);

  useEffect(() => {
    sel.current = selected;
    api.current?.gs.highlight(selected);
    api.current?.redraw();
  }, [selected, status]);

  return {
    status,
    flyTo(mode) {
      const a = api.current;
      if (!a) return;
      if (typeof mode === "string") { a.fly(fitView(a.gs.center, a.gs.size.x, a.gs.size.z, a.aspect(), mode)); return; }
      const r = a.gs.rooms.find((x) => x.id === mode.room);
      if (r) a.fly(roomView(r, a.aspect()));
    },
  };
}
