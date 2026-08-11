# Product context

## Recording identity

A recording is identified by its Spotify URI. Matching titles are not interchangeable: live,
remastered, clean, explicit, edited, sped-up, and re-recorded releases remain distinct.

## Observed writes

An observed write is a Spotify mutation followed by evidence about the accepted or resulting
state. A snapshot proves an item mutation was accepted. A fresh metadata read verifies a metadata
mutation. Missing evidence produces an explicit `ambiguous` or `mismatch` result and must not cause
an automatic retry.

## Playlist order

Playlist order is a sequence of positions, not a set of track IDs. Duplicate recordings retain
separate position identities. Plans are tied to a Spotify snapshot and cannot apply to a changed
source order.

## Analysis provenance

Every audio field records where it came from. Missing data stays missing. Provider disagreement is
reported instead of silently choosing a value, and user overrides apply only to the exact recording
they name.

## Durable plans

DJ analyses and plans are immutable, content-addressed records. Mutation receipts have stable
identity and advance as Spotify writes are observed, allowing partial work to be diagnosed and a
verified previous order to be restored.
