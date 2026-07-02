// Реестр пайплайнов/сценариев (ADR-0013). Декларативное описание пути: какие шаги, какая модель,
// какой промпт. Сейчас исполнение шагов — в оркестраторе (generation-job); реестр даёт версию пути
// в лог и точку расширения: новый сценарий (или смена модели Nano→GPT→ControlNet) = новая запись тут
// + провайдер под шаг. Меняешь состав/модель/промпт шага → бампни version.

export type PipelineStepDef = {
  name: string;
  kind: "vision" | "image" | "text";
  provider: string; // логический id провайдера под шаг
  promptId: string;
};

export type PipelineDef = {
  id: string;
  version: string;
  title: string;
  steps: PipelineStepDef[];
};

export const DEFAULT_PIPELINE = "preview-v1";

export const PIPELINES: Record<string, PipelineDef> = {
  "preview-v1": {
    id: "preview-v1",
    version: "v1",
    title: "Превью: анализ фото → restyle в стиле → идеи",
    steps: [
      { name: "analyze", kind: "vision", provider: "gemini", promptId: "room-analysis" },
      { name: "restyle", kind: "image", provider: "gemini", promptId: "restyle" },
      { name: "ideas", kind: "text", provider: "gemini", promptId: "ideas" },
    ],
  },
};

export function getPipeline(id: string = DEFAULT_PIPELINE): PipelineDef {
  return PIPELINES[id] ?? PIPELINES[DEFAULT_PIPELINE]!;
}
