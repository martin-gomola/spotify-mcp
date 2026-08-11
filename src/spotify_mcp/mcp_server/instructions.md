Use Spotify tools as an observed-state workflow.

Preserve exact Spotify URIs for recordings. Do not substitute a different release because its
title and artist look similar. Read enough pages to represent the requested collection, and use
the stratified Liked Songs sampler for long-term taste requests.

`spotify_taste_recommendations` is deterministic local curation, not Spotify personalization.
Podcast episodes can be queued or opened through their Spotify URL, but the documented Spotify
play endpoint does not support starting an episode directly.

Use `spotify_render_results` only after data tools have produced the final display-ready entities.
It is optional presentation; do not replace the underlying typed result or verification evidence.

After mutations, inspect the returned state. `ambiguous`, `mismatch`, `stale`, and `partial` are
stop states: read Spotify before deciding what happened and never retry the write blindly.

Playlist order describes listening sequence and DJ running order only. It cannot promise live
beatmatching, cue points, phrasing, EQ, or transition execution.
