export type ResultKind = "track" | "album" | "artist" | "playlist" | "episode" | "show";

export interface SpotifyResultItem {
  name: string;
  spotify_url: string;
  subtitle?: string | null;
  kind: ResultKind;
  reason?: string | null;
}

export interface SpotifyResultsPayload {
  title: string;
  items: SpotifyResultItem[];
}

interface Device {
  id?: string | null;
  name: string;
  type: string;
  is_active: boolean;
  is_restricted: boolean;
}

interface PlaybackItem {
  uri?: string | null;
  spotify_url?: string | null;
}

interface NowPlaying {
  is_playing: boolean;
  context_uri?: string | null;
  device?: Device | null;
  item?: PlaybackItem | null;
}

interface ResultsContext {
  devices: Device[];
  selected_device_id?: string | null;
  requires_device_selection: boolean;
  has_usable_devices: boolean;
  now_playing: NowPlaying;
}

interface ObservedPlaybackResult {
  status: "verified" | "unverified";
  requested_uri: string;
  device_id: string;
  observed: NowPlaying;
}

export interface ToolCallResult {
  structuredContent?: unknown;
  isError?: boolean;
  content?: Array<{ type: string; text?: string }>;
}

export interface ResultsBridge {
  callServerTool(name: string, args: Record<string, unknown>): Promise<ToolCallResult>;
  openLink(url: string): Promise<{ isError?: boolean }>;
}

interface CardView {
  element: HTMLElement;
  item: SpotifyResultItem;
  playButton?: HTMLButtonElement;
  status: HTMLParagraphElement;
}

const PLAYABLE_KINDS = new Set<ResultKind>(["track", "album", "artist", "playlist"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isResultsPayload(value: unknown): value is SpotifyResultsPayload {
  return (
    isObject(value)
    && typeof value.title === "string"
    && Array.isArray(value.items)
  );
}

function payloadKey(payload: SpotifyResultsPayload): string {
  return JSON.stringify([
    payload.title,
    payload.items.map((item) => [
      item.name,
      item.spotify_url,
      item.subtitle ?? null,
      item.kind,
      item.reason ?? null,
    ]),
  ]);
}

function toolErrorMessage(result: ToolCallResult): string {
  const text = result.content?.find((item) => item.type === "text" && item.text)?.text;
  return text || "Spotify could not complete this action.";
}

function spotifyUrlFromUri(uri: string | null | undefined): string | null {
  if (!uri) return null;
  const parts = uri.split(":");
  if (parts.length !== 3 || parts[0] !== "spotify") return null;
  return `https://open.spotify.com/${parts[1]}/${parts[2]}`;
}

function addText(parent: HTMLElement, className: string, value: string | null | undefined): void {
  if (!value?.trim()) return;
  const element = document.createElement("p");
  element.className = className;
  element.textContent = value;
  parent.appendChild(element);
}

export class SpotifyResultsView {
  readonly #bridge: ResultsBridge;
  readonly #title: HTMLElement;
  readonly #device: HTMLElement;
  readonly #summary: HTMLElement;
  readonly #results: HTMLElement;
  readonly #feedback: HTMLElement;
  #cards: CardView[] = [];
  #selectedDeviceId: string | null = null;
  #inFlight = false;
  #renderRevision = 0;
  #lastPayloadKey: string | null = null;
  #lastRender: Promise<void> | null = null;

  constructor(bridge: ResultsBridge) {
    this.#bridge = bridge;
    this.#title = document.querySelector<HTMLElement>("#title")!;
    this.#device = document.querySelector<HTMLElement>("#device")!;
    this.#summary = document.querySelector<HTMLElement>("#summary")!;
    this.#results = document.querySelector<HTMLElement>("#results")!;
    this.#feedback = document.querySelector<HTMLElement>("#feedback")!;
  }

  render(payload: unknown): Promise<void> {
    if (!isResultsPayload(payload)) return Promise.resolve();
    const nextPayloadKey = payloadKey(payload);
    if (nextPayloadKey === this.#lastPayloadKey) {
      return this.#lastRender ?? Promise.resolve();
    }
    this.#lastPayloadKey = nextPayloadKey;
    const revision = ++this.#renderRevision;
    this.#title.textContent = payload.title;
    this.#summary.textContent = `${payload.items.length} result${payload.items.length === 1 ? "" : "s"}`;
    this.#feedback.replaceChildren();
    this.#results.replaceChildren();
    this.#cards = payload.items.map((item) => this.#renderCard(item));
    this.#lastRender = this.#loadContext(revision);
    return this.#lastRender;
  }

  #renderCard(item: SpotifyResultItem): CardView {
    const card = document.createElement("article");
    card.className = "card";
    card.dataset.spotifyUrl = item.spotify_url;

    const copy = document.createElement("div");
    copy.className = "copy";
    addText(copy, "name", item.name);
    const meta = [item.kind, item.subtitle].filter((value) => value?.trim()).join(" — ");
    addText(copy, "meta", meta);
    addText(copy, "reason", item.reason);
    const status = document.createElement("p");
    status.className = "card-status";
    status.setAttribute("aria-live", "polite");
    copy.appendChild(status);
    card.appendChild(copy);

    const actions = document.createElement("div");
    actions.className = "actions";
    let playButton: HTMLButtonElement | undefined;
    if (PLAYABLE_KINDS.has(item.kind)) {
      playButton = document.createElement("button");
      playButton.type = "button";
      playButton.className = "play";
      playButton.textContent = "Play";
      playButton.disabled = true;
      playButton.setAttribute("aria-label", `Play ${item.name}${item.subtitle ? ` — ${item.subtitle}` : ""}`);
      playButton.addEventListener("click", () => void this.#play(item, status));
      actions.appendChild(playButton);
    }

    const openLink = document.createElement("a");
    openLink.className = "open-link";
    openLink.href = item.spotify_url;
    openLink.target = "_blank";
    openLink.rel = "noopener noreferrer";
    openLink.textContent =
      item.kind === "episode" || item.kind === "show" ? `Open ${item.kind}` : "Open Spotify";
    openLink.setAttribute("aria-label", `Open ${item.name} in Spotify`);
    openLink.addEventListener("click", (event) => void this.#openExternal(event, item.spotify_url));
    actions.appendChild(openLink);
    card.appendChild(actions);
    this.#results.appendChild(card);
    return { element: card, item, playButton, status };
  }

  async #loadContext(revision: number): Promise<void> {
    this.#device.textContent = "Loading devices...";
    try {
      const result = await this.#bridge.callServerTool("spotify_results_context", {});
      if (revision !== this.#renderRevision) return;
      if (result.isError || !isObject(result.structuredContent)) {
        this.#setFeedback(toolErrorMessage(result), "error");
        this.#device.textContent = "Playback unavailable";
        return;
      }
      const context = result.structuredContent as unknown as ResultsContext;
      this.#applyContext(context);
    } catch {
      if (revision !== this.#renderRevision) return;
      this.#device.textContent = "Playback unavailable";
      this.#setFeedback("Spotify playback controls are unavailable in this client.", "error");
    }
  }

  #applyContext(context: ResultsContext): void {
    const usable = context.devices.filter((device) => Boolean(device.id) && !device.is_restricted);
    this.#selectedDeviceId = context.selected_device_id || null;
    this.#device.replaceChildren();
    this.#setFeedback("");

    if (!context.has_usable_devices || usable.length === 0) {
      this.#device.textContent = "No controllable device";
      this.#setFeedback("Open Spotify on a device to play here.", "error");
    } else if (context.requires_device_selection) {
      const wrapper = document.createElement("label");
      wrapper.className = "device-choice";
      wrapper.textContent = "Play on";
      const select = document.createElement("select");
      select.setAttribute("aria-label", "Spotify playback device");
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Choose device";
      select.appendChild(placeholder);
      for (const device of usable) {
        const option = document.createElement("option");
        option.value = device.id!;
        option.textContent = `${device.name}${device.is_active ? " (currently active)" : ""}`;
        select.appendChild(option);
      }
      select.addEventListener("change", () => {
        this.#selectedDeviceId = select.value || null;
        this.#syncPlayButtons();
      });
      wrapper.appendChild(select);
      this.#device.appendChild(wrapper);
    } else {
      const selected = usable.find((device) => device.id === this.#selectedDeviceId);
      const prefix = context.now_playing.is_playing ? "Playing on" : "Play on";
      this.#device.textContent = selected ? `${prefix} ${selected.name}` : "Spotify device ready";
    }

    this.#markObservedPlayback(context.now_playing);
    this.#syncPlayButtons();
  }

  async #play(item: SpotifyResultItem, status: HTMLParagraphElement): Promise<void> {
    if (this.#inFlight || !this.#selectedDeviceId) return;
    this.#inFlight = true;
    status.textContent = "Starting...";
    status.dataset.state = "starting";
    status.removeAttribute("role");
    this.#setFeedback("");
    this.#syncPlayButtons();
    try {
      const result = await this.#bridge.callServerTool("spotify_results_play", {
        spotify_url: item.spotify_url,
        device_id: this.#selectedDeviceId,
      });
      if (result.isError || !isObject(result.structuredContent)) {
        status.textContent = toolErrorMessage(result);
        status.dataset.state = "error";
        status.setAttribute("role", "alert");
        return;
      }
      const playback = result.structuredContent as unknown as ObservedPlaybackResult;
      if (playback.status !== "verified") {
        status.textContent = "Playback requested, but Spotify did not confirm this item.";
        status.dataset.state = "error";
        status.setAttribute("role", "alert");
        return;
      }
      this.#clearCurrentCard();
      const current = this.#cards.find((card) => card.item.spotify_url === item.spotify_url);
      if (current) {
        current.element.setAttribute("aria-current", "true");
        current.status.textContent = "Playing";
        current.status.dataset.state = "verified";
        current.status.removeAttribute("role");
      }
      const deviceName = playback.observed.device?.name;
      if (deviceName) this.#device.textContent = `Playing on ${deviceName}`;
    } catch {
      status.textContent = "Spotify could not start playback.";
      status.dataset.state = "error";
      status.setAttribute("role", "alert");
    } finally {
      this.#inFlight = false;
      this.#syncPlayButtons();
    }
  }

  #markObservedPlayback(nowPlaying: NowPlaying): void {
    if (!nowPlaying.is_playing) return;
    const observedUrl = nowPlaying.item?.spotify_url || spotifyUrlFromUri(nowPlaying.context_uri);
    if (!observedUrl) return;
    const card = this.#cards.find((candidate) => candidate.item.spotify_url === observedUrl);
    if (!card) return;
    card.element.setAttribute("aria-current", "true");
    card.status.textContent = "Playing";
    card.status.dataset.state = "verified";
  }

  #clearCurrentCard(): void {
    for (const card of this.#cards) {
      card.element.removeAttribute("aria-current");
      if (card.status.dataset.state === "verified") {
        card.status.replaceChildren();
        delete card.status.dataset.state;
      }
    }
  }

  #syncPlayButtons(): void {
    for (const card of this.#cards) {
      if (card.playButton) {
        card.playButton.disabled = this.#inFlight || !this.#selectedDeviceId;
      }
    }
  }

  async #openExternal(event: MouseEvent, url: string): Promise<void> {
    event.preventDefault();
    try {
      const result = await this.#bridge.openLink(url);
      if (result.isError) this.#setFeedback("The host could not open Spotify.", "error");
    } catch {
      this.#setFeedback("The host could not open Spotify.", "error");
    }
  }

  #setFeedback(message: string, state?: "error"): void {
    this.#feedback.textContent = message;
    if (state) this.#feedback.dataset.state = state;
    else delete this.#feedback.dataset.state;
  }
}
