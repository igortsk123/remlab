// Фейковый провайдер для тестов/e2e и локального запуска без трат на ИИ (флаг REMLAB_FAKE_AI=1).
// Возвращает детерминированные заглушки в тех же контрактах, что и реальный провайдер.

import { ok } from "@/lib/result";
import type { ImageProvider, VisionProvider } from "@/lib/providers/types";

// 1x1 PNG (валидная картинка-заглушка).
const PIXEL_PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

const FAKE_ANALYSIS = JSON.stringify({
  summary: "Светлая гостиная с диваном у окна; много естественного света.",
  objects: [
    { label: "Диван", action: "keep" },
    { label: "Окно", action: "keep" },
    { label: "Шторы", action: "suggest_change" },
    { label: "Освещение", action: "suggest_change" },
  ],
});

const FAKE_IDEAS = JSON.stringify({
  ideas: [
    { title: "Тёплый текстиль", detail: "Ковёр и шторы в природной палитре." },
    { title: "Сценарный свет", detail: "Торшер тёплого спектра вместо верхнего света." },
    { title: "Зелень", detail: "Крупное растение у окна." },
    { title: "Акцент над диваном", detail: "Постер в раме задаёт характер." },
  ],
});

export function createFakeProvider(): ImageProvider & VisionProvider {
  return {
    id: "fake",
    imageModel: "fake-image",
    textModel: "fake-text",
    async generateText() {
      return ok(FAKE_IDEAS);
    },
    async analyze() {
      return ok(FAKE_ANALYSIS);
    },
    async generateImage() {
      return ok({ mimeType: "image/png", base64: PIXEL_PNG });
    },
  };
}
