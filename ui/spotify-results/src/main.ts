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

let connected = false;
let hasPendingPayload = false;
let pendingPayload: unknown;

function renderWhenConnected(payload: unknown): void {
  if (!connected) {
    pendingPayload = payload;
    hasPendingPayload = true;
    return;
  }
  void view.render(payload);
}

app.addEventListener("toolinput", (input) => {
  renderWhenConnected(input.arguments);
});

app.addEventListener("toolresult", (result) => {
  renderWhenConnected(result.structuredContent);
});

window.addEventListener("openai:set_globals", (event) => {
  const detail = (event as CustomEvent<{ globals?: { toolOutput?: unknown } }>).detail;
  renderWhenConnected(detail?.globals?.toolOutput ?? window.openai?.toolOutput);
});

// app.connect() may fire "toolinput" synchronously before returning,
// so listeners must be registered first. The connected flag + pending
// buffer above ensure any such event is captured and flushed below.
await app.connect();
connected = true;

if (window.openai?.toolOutput) {
  await view.render(window.openai.toolOutput);
}
if (hasPendingPayload) {
  const payload = pendingPayload;
  hasPendingPayload = false;
  pendingPayload = undefined;
  await view.render(payload);
}
