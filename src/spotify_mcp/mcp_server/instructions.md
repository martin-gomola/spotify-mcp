Preserve exact Spotify URIs and recording identities. Use the narrowest tool for the request and
page only as far as needed. Generic library tools require full Spotify URIs.

Inspect every mutation result. `ambiguous`, `mismatch`, `stale`, and `partial` are stop states:
re-read Spotify before deciding what happened and never retry a write blindly.

Render results once, only after the final playable entities are verified; otherwise return their
canonical Spotify links. Podcast episodes are queue/link flows, not direct play requests.
`spotify_taste_recommendations` is local deterministic curation, not Spotify personalization.
Playlist order cannot promise live mixing, EQ, cue points, or transitions.
