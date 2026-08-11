import { expect, it, vi } from "vitest";

const appState = vi.hoisted(() => ({
  toolInput: undefined as Record<string, unknown> | undefined,
  instances: [] as Array<{
    listeners: Map<string, (payload: Record<string, unknown>) => void>;
    callServerTool: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("@modelcontextprotocol/ext-apps", () => ({
  App: class {
    listeners = new Map<string, (payload: Record<string, unknown>) => void>();
    callServerTool = vi.fn(async () => ({
      structuredContent: {
        devices: [],
        selected_device_id: null,
        requires_device_selection: false,
        has_usable_devices: false,
        now_playing: { is_playing: false },
      },
    }));

    constructor() {
      appState.instances.push(this);
    }

    addEventListener(name: string, listener: (payload: Record<string, unknown>) => void): void {
      this.listeners.set(name, listener);
    }

    async connect(): Promise<void> {
      const listener = this.listeners.get("toolinput");
      if (listener && appState.toolInput) listener({ arguments: appState.toolInput });
    }

    async openLink(): Promise<Record<string, never>> {
      return {};
    }
  },
}));

it("renders the first result from tool input and deduplicates the later tool result", async () => {
  document.body.innerHTML = `
    <header><h1 id="title"></h1><div id="device"></div></header>
    <p id="summary">Preparing results...</p>
    <main id="results"></main>
    <p id="feedback"></p>
  `;
  appState.instances.length = 0;
  delete (window as Window & { openai?: unknown }).openai;
  const payload = {
    title: "Top song",
    items: [
      {
        name: "Track One",
        spotify_url: "https://open.spotify.com/track/track-1",
        kind: "track",
      },
    ],
  };
  appState.toolInput = payload;

  await import("./main");
  const app = appState.instances[0]!;
  await vi.waitFor(() => expect(document.querySelector("#title")?.textContent).toBe("Top song"));
  expect(document.querySelectorAll(".card")).toHaveLength(1);

  app.listeners.get("toolresult")!({ structuredContent: structuredClone(payload) });
  await vi.waitFor(() => expect(app.callServerTool).toHaveBeenCalledTimes(1));
});
