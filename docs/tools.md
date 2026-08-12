# Tool catalog

Spotify MCP exposes 55 model-visible structured tools. Asterisks in the input column mark required
fields; all other inputs are optional and use the defaults shown below.

## Status and discovery

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_status` | None | Spotify read when configured | Return actionable configuration details before setup. When configured, validate the saved authentication and return `authenticated=false` when the local grant is missing or expired. |
| `spotify_search` | `query*`, `item_type*`, `limit=10`, `offset=0` | Spotify read | Search one type: `track`, `album`, `artist`, `playlist`, `episode`, or `show`. Limit is 1–10. |
| `spotify_catalog` | `route*`, `entity_id*`, route-specific pagination | Spotify read | Route one exact read to track metadata, artist metadata, or an artist's paginated albums and singles. |
| `spotify_recently_played` | `limit=20` | Spotify read | Return up to 50 recently played tracks. |
| `spotify_top_tracks` | `time_range=medium_term`, `limit=20` | Spotify read | Return up to 50 top tracks for `short_term`, `medium_term`, or `long_term`. |
| `spotify_top_artists` | `time_range=medium_term`, `limit=20` | Spotify read | Return up to 50 top artists for a Spotify time range. Missing genre data remains `null`, not an inferred empty list. |

Search returns at most ten items per call even when Spotify reports a larger total. Increase
`offset` to request another page.

Primary Spotify entities include a canonical `spotify_url` such as
`https://open.spotify.com/track/...`. Clients can show these as links even when they do not support
the optional interactive result view.

## Taste rediscovery

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_taste_recommendations` | `limit=20` | Spotify reads + local deterministic ranking | Build up to 50 rediscovery suggestions from medium-term top tracks, recent plays, and a stratified Liked Songs sample. |

This tool reports `curation=local-deterministic` and `is_spotify_recommendation=false`. Its output
is reproducible from the observed source signals; it does not call Spotify's retired
recommendations endpoint and must not be described as Spotify-native personalization.

## Podcasts

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_podcast_discover` | `query*`, `limit=10`, `offset=0` | Spotify read | Search podcast shows and episodes together with canonical Spotify links. |
| `spotify_podcast_show` | `show_id*` | Spotify read | Return typed metadata for one exact show. |
| `spotify_podcast_show_episodes` | `show_id*`, `limit=20`, `offset=0` | Spotify read | Return one bounded page of episodes for a show. |
| `spotify_podcast_episode` | `episode_id*` | Spotify read | Return one exact episode. Preview evidence can be absent and no full audio is returned. |
| `spotify_saved_shows` | `limit=20`, `offset=0` | Spotify read | Return one page of shows saved by the current user. |
| `spotify_saved_episodes` | `limit=20`, `offset=0` | Spotify read | Return one page of episodes saved by the current user. |

Spotify's documented playback endpoint does not accept podcast episodes for direct start. Use
`spotify_add_to_queue` for an episode or open its `spotify_url` in Spotify. The server does not
pretend that an accepted track-play request proves unsupported episode playback.

## Playback

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_now_playing` | None | Spotify read | Return playback state, current item, device, progress, shuffle, and repeat state. |
| `spotify_devices` | None | Spotify read | List available Spotify Connect devices. |
| `spotify_queue` | `limit=10` | Spotify read | Return the current item and up to 50 queued items. |
| `spotify_play` | `uri`, `item_type` + `item_id`, or `query` + `item_type`; `device_id`, `offset` | Spotify read, then conditional write for queries; Spotify write for exact identity | Start a track, album, artist, or playlist. Query playback writes only when the top ten results contain exactly one exact name or exact name-and-artist match; otherwise it returns URI-preserving candidates for explicit selection. For a track, `offset` is milliseconds; for a context it is the item position. |
| `spotify_resume` | `device_id` | Spotify write | Resume playback. |
| `spotify_pause` | `device_id` | Spotify write | Pause playback. |
| `spotify_next` | `device_id` | Spotify write | Skip to the next item. |
| `spotify_previous` | `device_id` | Spotify write | Skip to the previous item. |
| `spotify_add_to_queue` | `uri` or `item_type` + `item_id`, `device_id` | Spotify write | Queue one `track` or podcast `episode`. |
| `spotify_set_volume` | `volume_percent*`, `device_id` | Spotify write | Set device volume from 0 through 100. |
| `spotify_adjust_volume` | `adjustment*`, `device_id` | Spotify write | Add or subtract relative volume on the selected device, clamped to 0 through 100. |
| `spotify_seek` | `position_ms*`, `device_id` | Idempotent Spotify write | Seek to an exact non-negative millisecond position in the current item. |
| `spotify_set_shuffle` | `state*`, `device_id` | Idempotent Spotify write | Enable or disable shuffle. |
| `spotify_set_repeat` | `repeat_state*`, `device_id` | Idempotent Spotify write | Set repeat to `track`, `context`, or `off`. |
| `spotify_transfer_playback` | `device_id*`, `play=false` | Idempotent Spotify write | Transfer Spotify Connect to one explicit controllable device, optionally starting playback. |

When `device_id` is omitted, the server uses the active controllable device or the only
controllable device. When multiple inactive controllable devices exist, it returns an error that
requires an explicit `device_id`; restricted devices and devices without IDs are never selected.
It transfers Spotify Connect to an unambiguous selected device when necessary. Playback write
results mean Spotify accepted the API request; they are not a subsequent playback-state
verification.

## Liked Songs

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_saved_tracks` | `limit=50`, `offset=0` | Spotify read | Return one page of Liked Songs with saved date and stable library position. Limit is 1–50. |
| `spotify_sample_liked_songs` | `sample_size=48` | Spotify read | Return a deterministic, stratified sample spanning the complete saved-history range. Size is 8–100. |
| `spotify_library_contains` | `uris*` | Spotify read | Check up to 40 exact track, album, show, episode, or audiobook URIs. |
| `spotify_library_save` | `uris*` | Spotify write + read verification | Save up to 40 exact supported library URIs and verify their observed state once. |
| `spotify_library_remove` | `uris*` | Destructive Spotify write + read verification | Remove up to 40 exact supported library URIs and verify their observed state once. There is no automatic undo. |

`spotify_sample_liked_songs` is intended for taste-based playlist work. It samples across the
history; it is not a complete library audit. Page through `spotify_saved_tracks` for a complete
scan.

## Albums

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_albums` | `album_ids*` | Spotify read | Fetch typed metadata for up to 20 exact albums. Unknown IDs are returned separately. |
| `spotify_album_tracks` | `album_id*`, `limit=20`, `offset=0` | Spotify read | Return one page of tracks from an exact album. Limit is 1–50. |
| `spotify_saved_albums` | `limit=20`, `offset=0` | Spotify read | Return one page of albums saved in the current user's library. Limit is 1–50. |
Album tools accept bare album IDs or `spotify:album:...` URIs. `spotify_albums` uses supported
singular album requests with bounded concurrency rather than Spotify's retired batch-albums
endpoint.

Use the generic library tools above for album save, remove, and membership operations. They require
full Spotify URIs so mixed entity types remain explicit and exact.

## Playlists

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_playlists` | `limit=50`, `offset=0` | Spotify read | Return one page of the current user's playlists. Limit is 1–50. |
| `spotify_playlist` | `playlist_id*` | Spotify read | Return exact playlist metadata, owner, URL, visibility, and snapshot. |
| `spotify_playlist_items` | `playlist_id*`, `limit=50`, `offset=0` | Spotify read | Return one page of tracks and podcast episodes with one-based playlist positions. |
| `spotify_playlist_create` | `name*`, `description=""`, `public=false` | Spotify write + visibility verification | Create a playlist, private by default, then re-read its observed visibility. |
| `spotify_playlist_update` | `playlist_id*`, requested metadata fields | Spotify write + read verification | Update `name`, `description`, `public`, or `collaborative`, then verify requested fields once. |
| `spotify_playlist_add` | `playlist_id*`, `item_ids_or_uris*`, `position` | Spotify write | Add up to 100 track IDs or track/episode URIs. A returned snapshot proves request acceptance. |
| `spotify_playlist_remove` | `playlist_id*`, `item_ids_or_uris*`, `snapshot_id` | Destructive Spotify write | Remove up to 100 exact items, optionally against a specific snapshot. |
| `spotify_playlist_reorder` | `playlist_id*`, `range_start*`, `insert_before*`, `range_length=1`, `snapshot_id` | Spotify write | Move one consecutive range using zero-based Spotify positions. |
| `spotify_playlist_unfollow` | `playlist_id*` | Destructive Spotify write + read verification | Remove a playlist from the user's library. Spotify does not expose permanent playlist deletion. |

Bare values in `item_ids_or_uris` are treated as track IDs. Use a full `spotify:episode:...` URI for
podcast episodes. For exact concurrency control, pass the most recently observed `snapshot_id` to
remove and reorder operations.

## Audio analysis

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_audio_features` | `track_ids*`, `source=auto`, `overrides` | Spotify and/or ReccoBeats read | Return field-level measurements and provenance for up to 100 exact recordings. |
| `spotify_audio_compare` | `track_ids*` | Spotify and ReccoBeats read | Compare both providers for up to 25 tracks without selecting a hidden winner. |
| `spotify_audio_audit` | `track_ids*`, `source=auto`, `overrides` | Spotify and/or ReccoBeats read | Summarize coverage, missing fields, and material conflicts for up to 100 tracks. |

`source` accepts `auto`, `spotify`, or `reccobeats`. Auto mode calls Spotify first and falls back to
ReccoBeats only when Spotify returns 403 or 404; it does not hide other Spotify failures. ReccoBeats
is an external provider and may return incomplete or heuristic data.

Overrides preserve the superseded provider observation. Each override requires `track_id` and may
set `tempo`, `key` (0–11), `mode` (0 or 1), `loudness`, or unit-interval fields such as `energy`,
`danceability`, and `valence`. Audio measurements are planning evidence, not musical-quality
scores.

## DJ planning

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_dj_analyze` | `playlist_id*`, `source=auto`, `missing_feature_policy=anchor`, `overrides`, `features` | Spotify and/or ReccoBeats read + local immutable write | Read every playlist item, enrich exact recordings automatically, apply explicit overrides last, verify the snapshot, and store an analysis artifact with provenance and coverage. |
| `spotify_dj_audit` | `playlist_id*`, `source=auto`, `overrides` | Spotify and/or ReccoBeats read | Audit the complete playlist for feature coverage, duplicates, tempo ambiguity, provider conflicts, and heuristic opening/peak/reset candidates. |
| `spotify_dj_plan` | `analysis_id*`, `energy_curve=warmup-build-peak-close`, `artist_spacing=3` | Local immutable write | Build a deterministic target order without changing Spotify. Curves: `warmup-build-peak-close`, `steady`, `rising`, or `waves`. |
| `spotify_dj_apply` | `plan_id*`, `expected_snapshot_id`, `dry_run=true` | Preview or Spotify reorder writes + local receipt | Check snapshot and exact order, preview by default, or apply the planned range moves. |
| `spotify_dj_restore` | `receipt_id*`, `expected_snapshot_id*`, `dry_run=true` | Preview or Spotify reorder writes + local receipt | Restore the exact pre-plan order recorded in a receipt. |
| `spotify_playlist_sort_by_bpm` | `playlist_id*`, `mode=tempoEnergy`, `dry_run=true`, `allow_partial=false`, `source=auto`, `overrides` | Preview or Spotify reorder writes + local receipt | Run the legacy-compatible stable BPM/energy sort while anchoring unavailable positions and using the shared verified mutation executor. |

DJ analysis automatically uses the shared audio-provider policy. Explicit `overrides` and legacy
`features` remain available; explicit values win without erasing provider provenance. Missing
values remain warnings with `anchor`, while `error` rejects incomplete analysis before storing an
artifact. Duplicate playlist entries use position-safe occurrence tokens. Provider measurements
are fetched live; no refresh option is exposed because this release does not cache them.

`spotify_playlist_sort_by_bpm` preserves the original compatibility modes: `tempoEnergy`, its
deprecated alias `dj`, `ascending`, and `descending`. It previews by default. With
`allow_partial=true`, positions without BPM remain fixed rather than being dropped or guessed.

If `expected_snapshot_id` is omitted from `spotify_dj_apply`, the plan's source snapshot is used.
Restore always requires the currently expected snapshot explicitly. Keep `dry_run=true` until the
preview, live snapshot, and target order are acceptable.

## Optional result presentation

| Tool | Inputs | Effect | Purpose |
| --- | --- | --- | --- |
| `spotify_render_results` | `title*`, `items*` | Local presentation; optional inline playback | Render 1–50 already-selected Spotify entities as compact cards inside Codex. |

Call the relevant data tools first, then prefer `spotify_render_results` for final, verified lists
of playable entities. Preserve available Spotify artwork and natural metadata such as artists,
album, duration, explicit status, owner, description, and collection size. A single playlist,
album, artist, or show uses a richer collection card. Longer result sets initially show six rows
with **Show more** disclosure.

Track, album, artist, and playlist cards can start the exact canonical entity on an explicit usable
device. When Spotify reports more than one controllable device, the card view requires a device
choice even if one is currently marked active. A card says **Playing** only after one of the bounded
fresh reads matches the requested item or context and device. If Spotify has not propagated matching
state yet, the card keeps the accepted request as pending confirmation without retrying the write.
Episodes and shows remain link-only, and every card keeps a secondary **Open in Spotify** action.

The renderer performs no discovery, ranking, verification of source data, or entity substitution.
Its two resource-bound playback controls are app-visible discovery surfaces and are intentionally
excluded from the model-facing tool count; that visibility metadata is not server authorization.
Clients without MCP Apps support still receive structured JSON, text, and canonical Spotify links.

## Safety and result states

The tools expose uncertainty instead of converting it into success:

- `verified`: a fresh read matched the requested library or metadata state.
- `mismatch`: a fresh read completed but did not match the requested state.
- `accepted`: Spotify returned the expected success evidence, such as a playlist snapshot or a
  successful playback response. This is not always a complete content re-read.
- `ambiguous`: the write may have succeeded, but the server could not prove the outcome. Read the
  relevant state before another write.
- `dry-run`: the DJ mutation was previewed and Spotify was not changed.
- `stale`: the live DJ playlist snapshot or exact order no longer matched the plan.
- `partial`: some DJ moves occurred, but final verification did not match the destination.
- `unchanged`: the DJ playlist already had the requested order.

Never repeat an `ambiguous` write automatically. For DJ `partial` or `stale` results, preserve the
receipt and returned snapshots and inspect the live playlist before applying or restoring anything
else.

## Shared limitations

- Spotify API availability, account product, application mode, market, and content restrictions
  still apply.
- Playback requires an available Spotify Connect device and may require Premium.
- List tools return bounded pages. A complete audit must follow `total` and `offset` until all pages
  are read.
- Search and audio providers can omit fields. The server returns missing data rather than inventing
  values.
- Spotify does not provide permanent playlist deletion through these tools; unfollow removes a
  playlist from the current user's library.
