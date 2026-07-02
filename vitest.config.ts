import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    include: ["tests/unit/**/*.test.ts"],
    environment: "node",
    // Ассеты трейса в тестах пишем в игнорируемый .vitest/ (не в репо/.data).
    env: { TRACE_DIR: ".vitest/traces" },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});
