import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: [fileURLToPath(new URL("./src/**/*.test.ts", import.meta.url))],
  },
});
