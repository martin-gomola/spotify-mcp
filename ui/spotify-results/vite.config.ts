import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin, type ResolvedConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const root = fileURLToPath(new URL(".", import.meta.url));
const output = fileURLToPath(
  new URL("../../src/spotify_mcp/mcp_server/resources", import.meta.url),
);
function trailingWhitespacePlugin(): Plugin {
  let config: ResolvedConfig;
  return {
    name: "trim-trailing-whitespace",
    configResolved(resolved) {
      config = resolved;
    },
    async closeBundle() {
      const asset = join(config.build.outDir, "spotify-results-v1.html");
      const html = await readFile(asset, "utf8");
      await writeFile(asset, html.replace(/[\t ]+$/gm, ""), "utf8");
    },
  };
}

export default defineConfig({
  root,
  plugins: [viteSingleFile(), trailingWhitespacePlugin()],
  build: {
    assetsInlineLimit: Number.POSITIVE_INFINITY,
    emptyOutDir: false,
    outDir: output,
    rollupOptions: {
      input: fileURLToPath(new URL("./spotify-results-v1.html", import.meta.url)),
    },
  },
});
