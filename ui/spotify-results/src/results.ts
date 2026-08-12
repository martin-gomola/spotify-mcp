export type ResultKind = "track" | "album" | "artist" | "playlist" | "episode" | "show";

export interface SpotifyResultItem {
  name: string;
  spotify_url: string;
  subtitle?: string | null;
  kind: ResultKind;
  reason?: string | null;
  image_url?: string | null;
  duration_ms?: number | null;
  explicit?: boolean | null;
  item_count?: number | null;
  description?: string | null;
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

interface PlaybackActionResult {
  operation: "pause";
  status: "accepted";
  device_id: string;
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
const COLLECTION_KINDS = new Set<ResultKind>(["album", "artist", "playlist", "show"]);
const INITIAL_VISIBLE_RESULTS = 6;
const RESULT_KINDS = new Set<ResultKind>([
  "track",
  "album",
  "artist",
  "playlist",
  "episode",
  "show",
]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function textList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item))
    : [];
}

function optionalInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function formatDuration(durationMs: number | null | undefined, compact = false): string | null {
  if (durationMs === null || durationMs === undefined) return null;
  const totalSeconds = Math.round(durationMs / 1000);
  if (compact) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }
  return `${Math.max(1, Math.round(totalSeconds / 60))} min`;
}

function itemCountLabel(item: SpotifyResultItem): string | null {
  if (item.item_count === null || item.item_count === undefined) return null;
  const noun = item.kind === "show" ? "episode" : "track";
  return `${item.item_count} ${noun}${item.item_count === 1 ? "" : "s"}`;
}

function normalizeResultItem(value: unknown): SpotifyResultItem | null {
  if (!isObject(value)) return null;
  const kind = value.kind ?? value.type;
  if (
    typeof value.name !== "string"
    || typeof value.spotify_url !== "string"
    || typeof kind !== "string"
    || !RESULT_KINDS.has(kind as ResultKind)
  ) {
    return null;
  }
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(value.spotify_url);
  } catch {
    return null;
  }
  const pathParts = parsedUrl.pathname.split("/").filter(Boolean);
  if (
    parsedUrl.protocol !== "https:"
    || parsedUrl.hostname !== "open.spotify.com"
    || parsedUrl.port
    || parsedUrl.username
    || parsedUrl.password
    || parsedUrl.search
    || parsedUrl.hash
    || pathParts.length !== 2
    || pathParts[0] !== kind
    || !pathParts[1]
  ) {
    return null;
  }
  const suppliedSubtitle = typeof value.subtitle === "string" ? value.subtitle.trim() : "";
  const derivedSubtitle = [
    textList(value.artists).join(", "),
    typeof value.album === "string" ? value.album : "",
    typeof value.owner === "string" ? value.owner : "",
    typeof value.release_date === "string" ? value.release_date : "",
  ].filter(Boolean).join(" • ");
  return {
    name: value.name,
    spotify_url: value.spotify_url,
    subtitle: suppliedSubtitle || derivedSubtitle || null,
    kind: kind as ResultKind,
    reason: typeof value.reason === "string" ? value.reason : null,
    image_url: typeof value.image_url === "string" ? value.image_url : null,
    duration_ms: optionalInteger(value.duration_ms),
    explicit: typeof value.explicit === "boolean" ? value.explicit : null,
    item_count: optionalInteger(value.item_count),
    description: typeof value.description === "string" ? value.description : null,
  };
}

function normalizeResultsPayload(value: unknown): SpotifyResultsPayload | null {
  if (!isObject(value) || typeof value.title !== "string" || !Array.isArray(value.items)) {
    return null;
  }
  const items = value.items.map(normalizeResultItem);
  if (items.some((item) => item === null)) return null;
  return { title: value.title, items: items as SpotifyResultItem[] };
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
      item.image_url ?? null,
      item.duration_ms ?? null,
      item.explicit ?? null,
      item.item_count ?? null,
      item.description ?? null,
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

function addArtwork(parent: HTMLElement, item: SpotifyResultItem, prominent: boolean): void {
  if (!item.image_url) return;
  parent.classList.add("has-artwork");
  const image = document.createElement("img");
  image.className = prominent ? "artwork artwork-prominent" : "artwork";
  image.src = item.image_url;
  image.alt = "";
  image.loading = prominent ? "eager" : "lazy";
  image.addEventListener("error", () => {
    image.remove();
    parent.classList.remove("has-artwork");
  }, { once: true });
  parent.appendChild(image);
}

function requireElement(selector: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(selector);
  if (!el) throw new Error(`SpotifyResultsView: required element "${selector}" not found`);
  return el;
}

export class SpotifyResultsView {
  readonly #bridge: ResultsBridge;
  readonly #title: HTMLElement;
  readonly #device: HTMLElement;
  #deviceLabel: HTMLElement | null = null;
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
    this.#title = requireElement("#title");
    this.#device = requireElement("#device");
    this.#summary = requireElement("#summary");
    this.#results = requireElement("#results");
    this.#feedback = requireElement("#feedback");
  }

  render(payload: unknown): Promise<void> {
    const normalizedPayload = normalizeResultsPayload(payload);
    if (!normalizedPayload) return Promise.resolve();
    const nextPayloadKey = payloadKey(normalizedPayload);
    if (nextPayloadKey === this.#lastPayloadKey) {
      return this.#lastRender ?? Promise.resolve();
    }
    this.#lastPayloadKey = nextPayloadKey;
    const revision = ++this.#renderRevision;
    this.#title.textContent = normalizedPayload.title;
    this.#summary.textContent = `${normalizedPayload.items.length} result${normalizedPayload.items.length === 1 ? "" : "s"}`;
    this.#feedback.replaceChildren();
    this.#results.replaceChildren();
    const isSingleCollection = normalizedPayload.items.length === 1
      && COLLECTION_KINDS.has(normalizedPayload.items[0]!.kind);
    this.#cards = normalizedPayload.items.map((item, index) =>
      this.#renderCard(item, isSingleCollection, index >= INITIAL_VISIBLE_RESULTS));
    if (normalizedPayload.items.length > INITIAL_VISIBLE_RESULTS) {
      this.#addResultsDisclosure(normalizedPayload.items.length);
    }
    this.#lastRender = this.#loadContext(revision);
    return this.#lastRender;
  }

  #renderCard(item: SpotifyResultItem, prominent: boolean, initiallyHidden: boolean): CardView {
    const card = document.createElement("article");
    card.className = prominent ? "card collection-card" : "card";
    if (item.kind === "track") card.classList.add("track-card");
    if (initiallyHidden) {
      card.classList.add("is-hidden");
      card.hidden = true;
    }
    card.dataset.spotifyUrl = item.spotify_url;

    addArtwork(card, item, prominent);

    const copy = document.createElement("div");
    copy.className = "copy";
    const itemHeading = document.createElement("div");
    itemHeading.className = "item-heading";
    addText(itemHeading, "name", item.name);
    if (item.explicit) {
      const explicit = document.createElement("span");
      explicit.className = "explicit-badge";
      explicit.textContent = "E";
      explicit.setAttribute("aria-label", "Explicit");
      itemHeading.appendChild(explicit);
    }
    copy.appendChild(itemHeading);
    const meta = [
      item.subtitle,
      itemCountLabel(item),
      formatDuration(item.duration_ms, item.kind === "track" || item.kind === "episode"),
    ].filter((value) => value?.trim()).join(" · ");
    addText(copy, "meta", meta);
    addText(copy, "reason", item.reason || (prominent ? item.description : null));
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
      playButton.setAttribute("aria-pressed", "false");
      playButton.setAttribute("aria-label", `Play ${item.name}${item.subtitle ? ` — ${item.subtitle}` : ""}`);
      playButton.addEventListener("click", () => {
        if (card.getAttribute("aria-current") === "true") {
          void this.#pauseCurrentCard();
        } else {
          void this.#play(item, status);
        }
      });
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

  #addResultsDisclosure(total: number): void {
    const footer = document.createElement("div");
    footer.className = "results-footer";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "show-more";
    button.textContent = `Show ${total - INITIAL_VISIBLE_RESULTS} more`;
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => {
      const expanded = button.getAttribute("aria-expanded") === "true";
      for (const card of this.#cards.slice(INITIAL_VISIBLE_RESULTS)) {
        card.element.hidden = expanded;
        card.element.classList.toggle("is-hidden", expanded);
      }
      button.setAttribute("aria-expanded", String(!expanded));
      button.textContent = expanded ? `Show ${total - INITIAL_VISIBLE_RESULTS} more` : "Show fewer";
    });
    footer.appendChild(button);
    this.#results.appendChild(footer);
  }

  async #loadContext(revision: number): Promise<void> {
    this.#device.textContent = "Loading devices...";
    try {
      const result = await this.#bridge.callServerTool("spotify_results_context", {});
      if (revision !== this.#renderRevision) return;
      if (result.isError || !isObject(result.structuredContent)) {
        this.#device.textContent = "Playback unavailable";
        this.#setContextError(toolErrorMessage(result), revision);
        return;
      }
      const context = result.structuredContent as unknown as ResultsContext;
      this.#applyContext(context);
    } catch {
      if (revision !== this.#renderRevision) return;
      this.#device.textContent = "Playback unavailable";
      this.#setContextError("Spotify playback controls are unavailable in this client.", revision);
    }
  }

  #setContextError(message: string, revision: number): void {
    this.#feedback.replaceChildren();
    const text = document.createTextNode(message);
    this.#feedback.appendChild(text);
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "retry";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => {
      this.#feedback.replaceChildren();
      delete this.#feedback.dataset.state;
      void this.#loadContext(revision);
    }, { once: true });
    this.#feedback.appendChild(retry);
    this.#feedback.dataset.state = "error";
  }

  #applyContext(context: ResultsContext): void {
    const usable = context.devices.filter((device) => Boolean(device.id) && !device.is_restricted);
    this.#selectedDeviceId = context.selected_device_id
      || (usable.length === 1 ? usable[0]!.id ?? null : null);
    this.#deviceLabel = null;
    this.#device.replaceChildren();
    this.#setFeedback("");

    if (!context.has_usable_devices || usable.length === 0) {
      this.#device.textContent = "No controllable device";
      this.#setFeedback("Open Spotify on a device to play here.", "error");
    } else {
      const wrapper = document.createElement("label");
      wrapper.className = "device-choice";
      const label = document.createElement("span");
      label.className = "device-choice-label";
      label.textContent = context.now_playing.is_playing && this.#selectedDeviceId
        ? "Playing on"
        : "Play on";
      this.#deviceLabel = label;
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
      select.value = this.#selectedDeviceId || "";
      select.addEventListener("change", () => {
        this.#selectedDeviceId = select.value || null;
        label.textContent = "Play on";
        this.#syncPlayButtons();
      });
      wrapper.appendChild(label);
      wrapper.appendChild(select);
      this.#device.appendChild(wrapper);
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
        status.textContent = "Playback request accepted; Spotify confirmation is still pending.";
        status.dataset.state = "pending";
        status.removeAttribute("role");
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
      if (this.#deviceLabel) this.#deviceLabel.textContent = "Playing on";
    } catch {
      status.textContent = "Spotify could not start playback.";
      status.dataset.state = "error";
      status.setAttribute("role", "alert");
    } finally {
      this.#inFlight = false;
      this.#syncPlayButtons();
    }
  }

  async #pauseCurrentCard(): Promise<void> {
    if (this.#inFlight || !this.#selectedDeviceId) return;
    const current = this.#cards.find((card) => card.element.getAttribute("aria-current") === "true");
    if (!current) return;
    const { status } = current;
    this.#inFlight = true;
    status.textContent = "Pausing...";
    status.dataset.state = "starting";
    status.removeAttribute("role");
    this.#setFeedback("");
    this.#syncPlayButtons();
    try {
      const result = await this.#bridge.callServerTool("spotify_results_pause", {
        device_id: this.#selectedDeviceId,
      });
      if (result.isError || !isObject(result.structuredContent)) {
        status.textContent = toolErrorMessage(result);
        status.dataset.state = "error";
        status.setAttribute("role", "alert");
        return;
      }
      const playback = result.structuredContent as unknown as PlaybackActionResult;
      if (playback.operation !== "pause" || playback.status !== "accepted") {
        status.textContent = "Spotify could not confirm the pause request.";
        status.dataset.state = "error";
        status.setAttribute("role", "alert");
        return;
      }
      this.#clearCurrentCard();
      status.textContent = "Paused";
      status.dataset.state = "paused";
      if (this.#deviceLabel) this.#deviceLabel.textContent = "Paused on";
    } catch {
      status.textContent = "Spotify could not pause playback.";
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
        const isPlaying = card.element.getAttribute("aria-current") === "true";
        card.playButton.textContent = isPlaying ? "Pause" : "Play";
        card.playButton.classList.toggle("is-pause", isPlaying);
        card.playButton.setAttribute("aria-pressed", String(isPlaying));
        card.playButton.setAttribute(
          "aria-label",
          `${isPlaying ? "Pause" : "Play"} ${card.item.name}${card.item.subtitle ? ` — ${card.item.subtitle}` : ""}`,
        );
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
