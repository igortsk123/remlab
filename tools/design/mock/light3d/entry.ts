// ПРОТОТИП СВЕТА 3D (T-20261111-22, не для прода). Тот же вход, что у бандла демо (`lib/viewer3d/demo-bundle.ts`), плюс классы
// three, которые нужны вставке `inject.js` (контактные тени, шторы, постобработка AO). Один экземпляр three на страницу: рендерер
// движка и объекты вставки — из одного модуля (иначе `RectAreaLight`/`UniformsLib` не видят друг друга).
export * from "@/lib/viewer3d/demo-bundle";
import {
  CanvasTexture,
  Color,
  DoubleSide,
  Group,
  HalfFloatType,
  Mesh,
  MeshBasicMaterial,
  MeshDepthMaterial,
  MeshStandardMaterial,
  OrthographicCamera,
  PlaneGeometry,
  RectAreaLight,
  ShaderMaterial,
  SRGBColorSpace,
  Vector2,
  Vector3,
  WebGLRenderTarget,
} from "three";
import { RectAreaLightUniformsLib } from "three/examples/jsm/lights/RectAreaLightUniformsLib.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { HorizontalBlurShader } from "three/examples/jsm/shaders/HorizontalBlurShader.js";
import { VerticalBlurShader } from "three/examples/jsm/shaders/VerticalBlurShader.js";

export const L3D = {
  CanvasTexture, Color, DoubleSide, Group, HalfFloatType, Mesh, MeshBasicMaterial, MeshDepthMaterial, MeshStandardMaterial, OrthographicCamera,
  PlaneGeometry, RectAreaLight, ShaderMaterial, SRGBColorSpace, Vector2, Vector3, WebGLRenderTarget, RectAreaLightUniformsLib,
  EffectComposer, GTAOPass, OutputPass, RenderPass, HorizontalBlurShader, VerticalBlurShader,
};
