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
  sendMessage: ReturnType<typeof vi.fn>;
} {
  return {
    callServerTool: vi.fn(async () => results.shift() ?? { isError: true }),
    openLink: vi.fn(async () => ({})),
    sendMessage: vi.fn(async () => ({})),
    canSendMessage: () => true,
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
  it("renders route approval quick actions and sends the selected response", async () => {
    const bridge = bridgeWith();
    await new SpotifyResultsView(bridge).render({
      view: "route_approval",
      title: "Approve the Bratislava route",
      summary: "2 pins · 1.2 km · about 25 minutes",
      pins: [
        { order: 1, name: "Michael's Gate", kind: "chapter", map_url: "https://maps.google.com/?q=1" },
        { order: 2, name: "Turn left", kind: "navigation", note: "Follow Venturska" },
      ],
      starting_point_url: "https://maps.google.com/?q=start",
      route_urls: ["https://maps.google.com/?q=route"],
    });

    expect(document.querySelectorAll(".route-pin")).toHaveLength(2);
    const actions = [...document.querySelectorAll<HTMLButtonElement>(".route-action")];
    expect(actions.map((button) => button.textContent)).toEqual(["Approve route", "Adjust pins"]);
    actions[0]!.click();
    expect(actions.every((button) => button.disabled)).toBe(true);
    await vi.waitFor(() => expect(bridge.sendMessage).toHaveBeenCalledWith(
      "I approve this route exactly as presented. Continue to the next required approval gate.",
    ));
    expect(bridge.callServerTool).not.toHaveBeenCalled();
  });

  it("disables route actions when the host lacks ui/message support", async () => {
    const bridge = bridgeWith();
    bridge.canSendMessage = () => false;
    await new SpotifyResultsView(bridge).render({
      view: "route_approval",
      title: "Approve route",
      summary: "1 pin",
      pins: [{ order: 1, name: "Start", kind: "chapter" }],
      route_urls: [],
    });

    const actions = [...document.querySelectorAll<HTMLButtonElement>(".route-action")];
    expect(actions.every((button) => button.disabled)).toBe(true);
    expect(document.querySelector("#feedback")?.textContent).toContain("Reply in chat");
  });

  it("does not render route payloads with credential-bearing links", async () => {
    const bridge = bridgeWith();
    await new SpotifyResultsView(bridge).render({
      view: "route_approval",
      title: "Unsafe route",
      summary: "1 pin",
      pins: [
        {
          order: 1,
          name: "Bad pin",
          kind: "chapter",
          map_url: "https://user:secret@127.0.0.1/route",
        },
      ],
      route_urls: [],
    });

    expect(document.querySelectorAll(".route-pin")).toHaveLength(0);
    expect(document.querySelectorAll(".route-action")).toHaveLength(0);
  });

  it("normalizes raw Spotify search results before rendering controls", async () => {
    const bridge = bridgeWith(contextResult());
    await new SpotifyResultsView(bridge).render({
      title: "Latest release",
      items: [
        {
          type: "track",
          name: "Everybody Scream",
          spotify_url: "https://open.spotify.com/track/track-1",
          artists: ["Florence + The Machine"],
          album: "Everybody Scream",
        },
      ],
    });

    expect(document.querySelector(".meta")?.textContent).toBe(
      "Florence + The Machine • Everybody Scream",
    );
    expect(document.querySelector("button.play")?.textContent).toBe("Play");
  });

  it("renders artwork and natural track metadata without repeating the entity kind", async () => {
    const bridge = bridgeWith(contextResult());
    await new SpotifyResultsView(bridge).render({
      title: "Running picks",
      items: [
        {
          type: "track",
          name: "Midnight City",
          spotify_url: "https://open.spotify.com/track/track-1",
          artists: ["M83"],
          album: "Hurry Up, We're Dreaming",
          image_url: "https://i.scdn.co/image/cover-1",
          duration_ms: 244_000,
          explicit: true,
        },
      ],
    });

    const image = document.querySelector<HTMLImageElement>("img.artwork");
    expect(image?.src).toBe("https://i.scdn.co/image/cover-1");
    expect(image?.alt).toBe("");
    expect(document.querySelector(".meta")?.textContent).toBe(
      "M83 • Hurry Up, We're Dreaming · 4:04",
    );
    expect(document.querySelector(".explicit-badge")?.getAttribute("aria-label")).toBe("Explicit");
  });

  it("renders one playlist as a richer collection card with natural summary metadata", async () => {
    const bridge = bridgeWith(contextResult());
    await new SpotifyResultsView(bridge).render({
      title: "Verified sunrise run",
      items: [
        {
          kind: "playlist",
          name: "Sunrise Run — 90 Minutes",
          spotify_url: "https://open.spotify.com/playlist/playlist-1",
          subtitle: "Liked Songs 2014–2026",
          image_url: "https://mosaic.scdn.co/640/cover",
          item_count: 23,
          duration_ms: 5_403_000,
          description: "Warm groove → house lift → indie crossover → cool-down",
        },
      ],
    });

    const card = document.querySelector(".card");
    expect(card?.classList.contains("collection-card")).toBe(true);
    expect(card?.classList.contains("has-artwork")).toBe(true);
    expect(card?.querySelector(".meta")?.textContent).toBe(
      "Liked Songs 2014–2026 · 23 tracks · 90 min",
    );
    expect(card?.querySelector(".reason")?.textContent).toContain("house lift");
  });

  it("shows six results initially and reveals the remaining rows on demand", async () => {
    const bridge = bridgeWith(contextResult());
    const items = Array.from({ length: 9 }, (_, index) => ({
      kind: "track" as const,
      name: `Track ${index + 1}`,
      spotify_url: `https://open.spotify.com/track/track-${index + 1}`,
    }));
    await new SpotifyResultsView(bridge).render({ title: "Nine tracks", items });

    const cards = [...document.querySelectorAll<HTMLElement>(".card")];
    const disclosure = document.querySelector<HTMLButtonElement>(".show-more")!;
    expect(cards).toHaveLength(9);
    expect(cards.filter((card) => !card.hidden)).toHaveLength(6);
    expect(disclosure.textContent).toBe("Show 3 more");

    disclosure.click();
    expect(cards.every((card) => !card.hidden)).toBe(true);
    expect(disclosure.getAttribute("aria-expanded")).toBe("true");
    expect(disclosure.textContent).toBe("Show fewer");

    disclosure.click();
    expect(cards.filter((card) => !card.hidden)).toHaveLength(6);
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
  });

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

  it("keeps a selected device changeable when one device is available", async () => {
    const bridge = bridgeWith(contextResult());
    await new SpotifyResultsView(bridge).render(TRACKS);

    const select = document.querySelector<HTMLSelectElement>(".device-choice select");
    expect(select).not.toBeNull();
    expect(select?.value).toBe("device-1");
    expect(select?.selectedOptions[0]?.textContent).toBe("Desk (currently active)");
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
    expect(document.querySelector(".device-choice-label")?.textContent).toBe("Playing on");
    expect(document.querySelector<HTMLSelectElement>(".device-choice select")?.value).toBe(
      "device-1",
    );
  });

  it("turns the active card control into Pause and pauses that device", async () => {
    const bridge = bridgeWith(
      contextResult({
        now_playing: {
          is_playing: true,
          device: { id: "device-1", name: "Desk", type: "Computer" },
          item: { spotify_url: TRACKS.items[0]!.spotify_url },
        },
      }),
      {
        structuredContent: {
          operation: "pause",
          status: "accepted",
          device_id: "device-1",
        },
      },
    );
    await new SpotifyResultsView(bridge).render(TRACKS);

    const button = document.querySelector<HTMLButtonElement>("button.play")!;
    expect(button.textContent).toBe("Pause");
    expect(button.getAttribute("aria-pressed")).toBe("true");

    button.click();
    await vi.waitFor(() => expect(button.textContent).toBe("Play"));

    expect(bridge.callServerTool).toHaveBeenLastCalledWith("spotify_results_pause", {
      device_id: "device-1",
    });
    expect(document.querySelector(".card")?.hasAttribute("aria-current")).toBe(false);
    expect(document.querySelector(".card-status")?.textContent).toBe("Paused");
    expect(document.querySelector(".device-choice-label")?.textContent).toBe("Paused on");
    expect(document.querySelector<HTMLSelectElement>(".device-choice select")?.value).toBe(
      "device-1",
    );
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
    expect(document.querySelector(".device-choice-label")?.textContent).toBe("Play on");
    expect(document.querySelector<HTMLSelectElement>(".device-choice select")?.value).toBe(
      "device-1",
    );
    expect(document.querySelector("#feedback")?.textContent).toBe("");
  });
});
