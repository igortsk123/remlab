import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Очередь тяжёлых прогонов DEV (tools/ops/heavy_slot.py, T-20261111-17/2) передаёт HEAVY_SLOT_CORES = ядер, на которые
// задача пущена: воркеров не больше (без этого vitest берёт nproc − 1 = 14 процессов на машине с 15 ядрами).
// Нет переменной (CI, прод-сборка, ручной запуск) — как прежде, по умолчанию vitest.
const SLOT_CORES = /^\d+$/.test(process.env.HEAVY_SLOT_CORES ?? "") ? Number(process.env.HEAVY_SLOT_CORES) : 0;
const SLOT_WORKERS = SLOT_CORES > 0 ? { maxWorkers: SLOT_CORES, minWorkers: SLOT_CORES } : {};

export default defineConfig({
  test: {
    include: ["tests/unit/**/*.test.ts"],
    environment: "node",
    ...SLOT_WORKERS,
    // Ассеты трейса в тестах пишем в игнорируемый .vitest/ (не в репо/.data).
    env: { TRACE_DIR: ".vitest/traces" },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});
