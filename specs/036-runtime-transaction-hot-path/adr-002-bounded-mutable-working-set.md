# ADR-002: Use a Store-Enforced Bounded Mutable Working Set

**Status:** Accepted
**Date:** 2026-09-29
**Deciders:** Repository architecture owner

## Context

The implementation uses a versioned working-set request to load the session
root, selected item and lease rows, active lease summaries, and append-only
buffers. The runtime kernel mutates that bounded payload in place. Earlier
planning text required a second explicit-delta DTO, but no current consumer
needs field-level merge or composition, and adding it would duplicate the
working-set shape without reducing the canonical state space.

The missing invariant was write-scope enforcement: a callback could inject a
pre-existing item or lease that was not selected and overwrite its canonical
row. This made the working set advisory rather than an executable boundary.

## Decision

Keep the bounded mutable working set and enforce its write scope in the store:

- session-root fields are part of every working set;
- a pre-existing item or lease may change only when its identity was selected;
- an operation may create a new item or lease identity;
- evidence, lease events, and outbox commands remain append-only transaction
  members;
- selected rows are compared by canonical fragment, so unchanged rows are not
  re-encoded;
- an attempted overwrite of an unselected existing identity fails with
  `PERSISTENCE_INVALID` before any row is written.

Adopt a separate explicit-delta DTO only if field-level merge,
cross-working-set composition, or external mutation providers become a real
requirement. That change would require a new architecture preflight.

## Options Considered

### Add an explicit-delta DTO now

This makes intended writes syntactically explicit, but duplicates item, lease,
evidence, and outbox structures already bounded by the request. It adds another
contract and conversion layer without a current composition consumer.

### Keep the bounded mutable working set without validation

This is the smallest implementation, but permits accidental writes outside the
declared selection and therefore does not provide a trustworthy boundary.

### Enforce scope around the bounded mutable working set (selected)

This retains the existing deterministic kernel interface, makes selection an
executable invariant, and keeps normalization and encoding proportional to the
selected or newly created rows.

## Consequences

- The store performs bounded existence checks for candidate item and lease
  identities before writing.
- Runtime callbacks remain simple and do not need a parallel patch builder.
- New identities are distinguishable from unauthorized overwrites.
- Tests must cover rejection without partial commit and unchanged canonical
  state.
- The public CLI, agent protocol, SQLite authority, and compatibility
  projection formats remain unchanged.
