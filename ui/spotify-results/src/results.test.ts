import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SpotifyResultsView,
  type ResultsBridge,
  type SpotifyResultsPayload,
  type ToolCallResult,
} from "./results";

const TRACKS: SpotifyResultsPayload = {
  title: "Top tracks",
  items: [
    {
      name: "Track One",
      spotify_url: "https://open.spotify.com/track/track-1",
      subtitle: "Artist One — Album One",
      kind: "track",
    },
    {
      name: "Track Two",
      spotify_url: "https://open.spotify.com/track/track-2",
      subtitle: "Artist Two — Album Two",
      kind: "track",
    },
    {
      name: "Episode One",
      spotify_url: "https://open.spotify.com/episode/episode-1",
      subtitle: "Show One",
      kind: "episode",
    },
  ],
};

function contextResult(overrides: Record<string, unknown> = {}): ToolCallResult {
  return {
    structuredContent: {
      devices: [
        {
          id: "device-1",
          name: "Desk",
          type: "Computer",
          is_active: true,
          is_restricted: false,
        },
      ],
      selected_device_id: "device-1",
      requires_device_selection: false,
      has_usable_devices: true,
      now_playing: { is_playing: false },
      ...overrides,
    },
  };
}

function verifiedResult(url = TRACKS.items[0]!.spotify_url): ToolCallResult {
  return {
    structuredContent: {
      status: "verified",
      requested_uri: url.replace("https://open.spotify.com/", "spotify:").replace("/", ":"),
      device_id: "device-1",
      observed: {
        is_playing: true,
        device: { id: "device-1", name: "Desk", type: "Computer" },
        item: { spotify_url: url },
      },
    },
  };
}

function renderShell(): void {
  document.body.innerHTML = `
    <header><h1 id="title"></h1><div id="device"></div></header>
    <p id="summary"></p>
    <main id="results"></main>
    <p id="feedback"></p>
  `;
}

function bridgeWith(...results: ToolCallResult[]): ResultsBridge & {
  callServerTool: ReturnType<typeof vi.fn>;
  openLink: ReturnType<typeof vi.fn>;
} {
  return {
    callServerTool: vi.fn(async () => results.shift() ?? { isError: true }),
    openLink: vi.fn(async () => ({})),
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  renderShell();
});

describe("SpotifyResultsView", () => {
  it("renders Play for playable items and keeps episodes link-only", async () => {
    const bridge = bridgeWith(contextResult());
    await new SpotifyResultsView(bridge).render(TRACKS);

    const cards = [...document.querySelectorAll<HTMLElement>(".card")];
    expect(cards).toHaveLength(3);
    expect(cards[0]!.querySelector("button.play")?.textContent).toBe("Play");
    expect(cards[0]!.querySelector("a.open-link")?.getAttribute("href")).toBe(
      TRACKS.items[0]!.spotify_url,
    );
    expect(cards[2]!.querySelector("button.play")).toBeNull();
    expect(cards[2]!.querySelector("a.open-link")?.textContent).toBe("Open episode");
    expect(cards[0]!.querySelector("button.play")?.getAttribute("aria-label")).toContain(
      "Track One",
    );
  });

  it("requires an explicit choice when several devices are available", async () => {
    const bridge = bridgeWith(
      contextResult({
        devices: [
          { id: "one", name: "One", type: "Computer", is_active: true, is_restricted: false },
          { id: "two", name: "Two", type: "Speaker", is_active: false, is_restricted: false },
        ],
        selected_device_id: null,
        requires_device_selection: true,
      }),
    );
    await new SpotifyResultsView(bridge).render(TRACKS);

    const play = document.querySelector<HTMLButtonElement>("button.play")!;
    const select = document.querySelector<HTMLSelectElement>("select")!;
    expect(play.disabled).toBe(true);
    expect(select.options[1]!.textContent).toBe("One (currently active)");
    select.value = "two";
    select.dispatchEvent(new Event("change"));
    expect(play.disabled).toBe(false);
  });

  it("marks a card Playing only after verified observed state", async () => {
    const bridge = bridgeWith(contextResult(), verifiedResult());
    await new SpotifyResultsView(bridge).render(TRACKS);

    document.querySelector<HTMLButtonElement>("button.play")!.click();
    await vi.waitFor(() => {
      expect(document.querySelector(".card")?.getAttribute("aria-current")).toBe("true");
    });
    expect(document.querySelector(".card-status")?.textContent).toBe("Playing");
    expect(bridge.callServerTool).toHaveBeenCalledTimes(2);
    expect(bridge.callServerTool).toHaveBeenLastCalledWith("spotify_results_play", {
      spotify_url: TRACKS.items[0]!.spotify_url,
      device_id: "device-1",
    });
  });

  it("allows only one playback request while a write is in flight", async () => {
    let resolvePlay!: (value: ToolCallResult) => void;
    const pending = new Promise<ToolCallResult>((resolve) => {
      resolvePlay = resolve;
    });
    const bridge: ResultsBridge & { callServerTool: ReturnType<typeof vi.fn> } = {
      callServerTool: vi
        .fn()
        .mockResolvedValueOnce(contextResult())
        .mockReturnValueOnce(pending),
      openLink: vi.fn(async () => ({})),
    };
    await new SpotifyResultsView(bridge).render(TRACKS);

    const buttons = [...document.querySelectorAll<HTMLButtonElement>("button.play")];
    buttons[0]!.click();
    buttons[1]!.click();
    expect(bridge.callServerTool).toHaveBeenCalledTimes(2);
    expect(buttons.every((button) => button.disabled)).toBe(true);
    resolvePlay(verifiedResult());
    await vi.waitFor(() => expect(buttons.every((button) => !button.disabled)).toBe(true));
  });

  it("preserves the previous Playing card when replacement is unverified", async () => {
    const bridge = bridgeWith(
      contextResult({
        now_playing: {
          is_playing: true,
          item: { spotify_url: TRACKS.items[0]!.spotify_url },
        },
      }),
      {
        structuredContent: {
          status: "unverified",
          requested_uri: "spotify:track:track-2",
          device_id: "device-1",
          observed: { is_playing: true },
        },
      },
    );
    await new SpotifyResultsView(bridge).render(TRACKS);

    const cards = [...document.querySelectorAll<HTMLElement>(".card")];
    const buttons = [...document.querySelectorAll<HTMLButtonElement>("button.play")];
    expect(cards[0]!.getAttribute("aria-current")).toBe("true");
    buttons[1]!.click();
    await vi.waitFor(() => expect(cards[1]!.querySelector(".card-status")?.textContent).toContain(
      "confirmation is still pending",
    ));
    expect(cards[0]!.getAttribute("aria-current")).toBe("true");
    expect(cards[1]!.querySelector(".card-status")?.getAttribute("data-state")).toBe("pending");
    expect(cards[1]!.querySelector(".card-status")?.getAttribute("role")).toBeNull();
    expect(bridge.callServerTool).toHaveBeenCalledTimes(2);
  });

  it("ignores repeated delivery of the same result payload", async () => {
    const pendingContext = deferred<ToolCallResult>();
    const bridge: ResultsBridge & { callServerTool: ReturnType<typeof vi.fn> } = {
      callServerTool: vi.fn(() => pendingContext.promise),
      openLink: vi.fn(async () => ({})),
    };
    const view = new SpotifyResultsView(bridge);

    const firstRender = view.render(TRACKS);
    const repeatedRender = view.render(structuredClone(TRACKS));

    expect(document.querySelectorAll(".card")).toHaveLength(3);
    expect(bridge.callServerTool).toHaveBeenCalledTimes(1);
    pendingContext.resolve(contextResult());
    await Promise.all([firstRender, repeatedRender]);
  });

  it("does not let an older context error overwrite newer results", async () => {
    const firstContext = deferred<ToolCallResult>();
    const secondContext = deferred<ToolCallResult>();
    const bridge: ResultsBridge & { callServerTool: ReturnType<typeof vi.fn> } = {
      callServerTool: vi
        .fn()
        .mockReturnValueOnce(firstContext.promise)
        .mockReturnValueOnce(secondContext.promise),
      openLink: vi.fn(async () => ({})),
    };
    const view = new SpotifyResultsView(bridge);
    const newerPayload: SpotifyResultsPayload = {
      title: "Newer results",
      items: [TRACKS.items[1]!],
    };

    const olderRender = view.render(TRACKS);
    const newerRender = view.render(newerPayload);
    secondContext.resolve(contextResult());
    await newerRender;
    firstContext.resolve({ isError: true, content: [{ type: "text", text: "Stale error" }] });
    await olderRender;

    expect(document.querySelector("#title")?.textContent).toBe("Newer results");
    expect(document.querySelectorAll(".card")).toHaveLength(1);
    expect(document.querySelector("#device")?.textContent).toBe("Play on Desk");
    expect(document.querySelector("#feedback")?.textContent).toBe("");
  });
});
