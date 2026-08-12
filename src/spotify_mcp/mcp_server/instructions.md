Use Spotify tools as an observed-state workflow.

Preserve exact Spotify URIs for recordings. Do not substitute a different release because its
title and artist look similar. Read enough pages to represent the requested collection, and use
the stratified Liked Songs sampler for long-term taste requests.

`spotify_taste_recommendations` is deterministic local curation, not Spotify personalization.
Podcast episodes can be queued or opened through their Spotify URL, but the documented Spotify
play endpoint does not support starting an episode directly.

For a simple find, show, or open request, call the narrow read tool and present its result directly.
Reserve playlist-building workflows for creation, curation, ordering, or mutation requests.

After data tools produce a final, verified list of playable entities, prefer
`spotify_render_results` when the client exposes it. Call it exactly once per response, only after
the complete final list is ready; never call it speculatively or retry it to refresh the display.
Preserve available `image_url`, artist, album, duration, explicit, owner, description, and item-count
metadata in the result items. A single playlist, album, artist, or show is presented as a richer
collection card; longer lists initially show six rows with an in-card disclosure control.
After playlist item writes, re-read the final playlist metadata before rendering so Spotify's
generated `image_url` is available when the API provides one.
Its inline cards can start the exact track, album, artist, or playlist on a selected Spotify
Connect device and verify playback with bounded fresh reads; they do not discover, rank, verify
source data, or substitute entities. Episodes and shows remain link/queue flows. Return canonical
Markdown links when MCP Apps are unavailable.

After mutations, inspect the returned state. `ambiguous`, `mismatch`, `stale`, and `partial` are
stop states: read Spotify before deciding what happened and never retry the write blindly.

Playlist order describes listening sequence and DJ running order only. It cannot promise live
beatmatching, cue points, phrasing, EQ, or transition execution.
