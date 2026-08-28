# Contributing

## Scope and design rules

- Keep expensive image work and desired-state decisions on the Docker host.
- Keep the Pi agent small, outbound-only, and limited to its fixed hardware target.
- Define cross-service payloads in `packages/contract/` before implementing either
  side of a protocol change.
- Keep originals immutable. Rendered previews and display artifacts are derived,
  versioned records.
- A preview must use the same renderer settings and display orientation as the
  artifact it represents.

## Development workflow

1. Copy `.env.example` to `.env` and set local values without committing it.
2. Use the Docker commands in the root README for dependencies and tests.
3. Update `uv.lock` with the dependency change and commit it with `pyproject.toml`
   changes.
4. Add or update tests for each behavioural change.
5. Run the focused test suite and `docker compose ... config` before handoff.

## Naming

- **Original asset**: immutable uploaded source image.
- **Rendered preview**: browser-visible result of a specific render request.
- **Display artifact**: immutable, checksummed file delivered to the Pi.
- **Display orientation**: physical installed direction of the e-ink panel.
- **Content framing**: crop, fit, padding, focal point, or flip applied to an image.

