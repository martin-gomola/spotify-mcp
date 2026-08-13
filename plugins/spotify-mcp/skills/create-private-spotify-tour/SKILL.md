---
name: create-private-spotify-tour
description: Create a chaptered private Spotify walking-tour episode from a destination or public tour URL, with an approved route and interactive map. Use when the user asks for a city audio tour, walking guide, tour podcast, VoiceMap-based route, or mapped Spotify travel episode. Avoid for ordinary document-to-podcast conversion, route extraction without audio, or generic trip planning.
---

# Create a private Spotify walking tour

Prepare and approve a grounded walking route, then delegate audio production to
`$create-private-spotify-podcast`. This skill owns tour discovery, route extraction, mapping, and
tour-specific metadata. It does not duplicate or weaken the private-podcast skill's source review,
Kokoro setup, content approvals, preview, upload, readiness, or playlist verification.

## Build and approve the route

1. When the user provides only a city, area, or landmark, invoke `find-tour` to discover and rank
   reusable public self-guided tours. Let it select a clear winner or present materially different
   candidates when the choice changes duration, terrain, accessibility, or theme.
2. When the user provides a specific tour URL, skip discovery and invoke `tour-path-extractor`
   directly. When `find-tour` selected a source, pass that canonical URL to
   `tour-path-extractor`.
3. Preserve the extractor's complete ordered route, navigation triggers, coordinate evidence,
   source conflicts, substitutions, and confidence. Never copy paid narration or treat an
   attraction-only shortlist as the full route.
4. Use the existing Google Maps tools to resolve grounded places, create the starting-point link,
   and build a walking-route link. If one link cannot retain every verified waypoint, return
   numbered route legs or a GPX/GeoJSON handoff instead of silently dropping stops. Use `mapy-com`
   when it offers a better outdoor, elevation, or waypoint handoff.
5. Present the route, chapter candidates, navigation-only triggers, and map for explicit approval
   before researching or scripting the episode. Call `spotify_render_route_approval` with every
   ordered pin and all route links so the MCP App renders the "Approve route" and "Adjust pins"
   response buttons. Do not leave the route-approval gate as a prose-only question. After the tool
   call, stop until the user selects an action or replies explicitly. Research landmark facts
   independently from credible sources; the discovered tour supplies route structure, not narration to copy.

## Prepare the podcast handoff

Use real values from the approved route. Keep the requested naming style, but do not claim a
30-minute tour when the verified duration is materially different.

```text
Podcast Episode Title:
[City/Spot Name]: The 30-Minute Secret Walking Tour

Episode Description / Show Notes:
📍 Starting Point: [Google Maps Pin Link]
⏱ Duration: [verified duration] | Distance: [verified distance]
🗺 Interactive Route Map: [Google Maps route, numbered legs, GPX, or web map]

TIMESTAMPS:
00:00 - Intro & Starting Point
[timestamp] - Stop 1: [chapter-worthy place]
[timestamp] - Stop 2: [chapter-worthy place]
...
```

Draft chapters from content stops, not navigation triggers. Keep routing cues in the narration only
where listeners need them to follow the walk.

## Produce the private episode

1. Give the independently researched source package, approved route, chapter plan, map links, and
   metadata requirements to `$create-private-spotify-podcast`.
2. Follow that skill's complete preflight and `$save-to-spotify` production workflow. Tour-route
   approval does not replace its plan approval, chapter approval, local preview, upload approval,
   audio validation, or exact `READY` gate.
3. Use Save to Spotify's timeline or Spotify episode chapters when supported. Always duplicate the
   chapter times in show notes so listeners can tap or seek directly to each stop.
4. Derive timestamps from the final assembled audio, never from estimated script positions. Verify
   that chapter labels, timestamps, route order, and stop names agree before upload.

Finish with the exact episode URI, readiness state, route-map link, starting-point link, and the
verified private playlist or private-show fallback reported by the production skill.
