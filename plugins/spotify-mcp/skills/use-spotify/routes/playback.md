# Playback route

- Read `spotify_now_playing`, `spotify_devices`, or `spotify_queue` only when that state is needed.
- Use `spotify_play` for an exact URI/ID or a narrowly resolved query.
- Use only the requested control: `spotify_resume`, `spotify_pause`, `spotify_next`,
  `spotify_previous`, `spotify_add_to_queue`, `spotify_set_volume`, `spotify_adjust_volume`,
  `spotify_seek`, `spotify_set_shuffle`, `spotify_set_repeat`, or `spotify_transfer_playback`.

When a device is required, prefer the active controllable device or an explicit user-selected ID.
An accepted playback write is not observed playback unless the result includes a fresh matching
read. Spotify exposes no EQ, crossfade, normalization, cue-point, or DSP control endpoint.
