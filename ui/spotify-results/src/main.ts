import { App } from "@modelcontextprotocol/ext-apps";

import { SpotifyResultsView, type ToolCallResult } from "./results";
import "./styles.css";

declare global {
  interface Window {
    openai?: {
      toolOutput?: unknown;
    };
  }
}

const app = new App(
  { name: "Spotify results", version: "1.0.0" },
  {},
  { autoResize: true, strict: true },
);

const view = new SpotifyResultsView({
  async callServerTool(name, args): Promise<ToolCallResult> {
    return app.callServerTool({ name, arguments: args }) as Promise<ToolCallResult>;
  },
  openLink(url) {
    return app.openLink({ url });
  },
});

app.addEventListener("toolresult", (result) => {
  void view.render(result.structuredContent);
});

window.addEventListener("openai:set_globals", (event) => {
  const detail = (event as CustomEvent<{ globals?: { toolOutput?: unknown } }>).detail;
  void view.render(detail?.globals?.toolOutput ?? window.openai?.toolOutput);
});

await app.connect();

if (window.openai?.toolOutput) {
  await view.render(window.openai.toolOutput);
}
