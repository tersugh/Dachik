# Dachik agent guide

`docs/ARCHITECTURE.md` is the authoritative architectural reference. This file gives concise working rules; it does not replace the architecture.

## Product purpose

Dachik is a privacy-first, independent internet data-usage sensor and ISP-accounting comparison tool. V1 measures a local macOS system; V2 extends the same accounting model to routers/gateways. Dachik reports evidence and limitations neutrally. Never automatically accuse an ISP of fraud or treat a discrepancy alone as proof of wrongdoing.

## Current V1 stack

- Python 3.12 collector and deterministic accounting engine
- FastAPI API bound to localhost
- SQLite as the only application database
- React + TypeScript + Vite frontend served locally in the user's browser
- pytest for Python tests
- appropriate frontend test, type-check, and lint tools when introduced

Do not add PostgreSQL, cloud accounts/sync, remote databases, native desktop shells, Network Extensions, or other deferred infrastructure during V1 unless the current task and architecture explicitly authorize it.

## Development principles

- Implement only the current development phase. Deferred architecture is not implementation authorization.
- Prefer the smallest correct, coherent change. Do not rewrite working components unnecessarily.
- Keep measurement/accounting logic separate from presentation logic.
- Keep OS-specific collection behind `TrafficProvider` adapter interfaces.
- Keep business and accounting rules out of React; enforce them in the backend/domain layer.
- Preserve one accounting model across macOS and future gateway providers.
- Do not modify unrelated files.

## Measurement integrity

- Never fabricate traffic measurements. Clearly isolate and label synthetic test data.
- Store and calculate usage internally as non-negative integer bytes.
- Preserve raw cumulative observations when appropriate; derive usage with deterministic, reproducible deltas.
- Never treat missing intervals as zero usage or silently extrapolate them.
- Detect and preserve counter resets, collector/OS restarts, interface changes, sampling gaps, and other discontinuities.
- Make ingestion idempotent and handle duplicate observations safely.
- Never double-count overlapping interfaces or measurement domains.
- Interface totals and per-process attribution are distinct domains. Never add per-process totals to interface totals.
- Local-device totals and future gateway/WAN totals are distinct boundaries. Never add them as independent usage when they observe the same traffic.
- Keep locally measured usage separate from ISP-reported usage.
- Every ISP comparison must expose its methodology, interval, units, measurement coverage, gaps, and limitations.
- Poor coverage reduces confidence in discrepancy conclusions. Insufficient coverage means insufficient evidence for a meaningful comparison.
- Reports must explain calculations and limitations. Agreement should be reported as agreement; never search for wrongdoing.

## Privacy

Collect only byte counters and the minimum metadata necessary for accounting and best-effort attribution.

Do not collect or persist:

- packet payloads;
- URLs, DNS history, browser history, or page titles;
- message contents or passwords;
- command-line arguments containing user information;
- browsing content of any kind.

Keep V1 local-first, with no cloud dependency or telemetry by default.

## Security

- Never commit secrets, `.env` files, SQLite databases, user-generated reports, credentials, or signing material.
- Bind the V1 API to loopback by default and preserve local-origin/request protections.
- Never expose router or ISP credentials to the frontend; use least-privilege backend storage such as Keychain when a later phase requires credentials.
- Avoid root privileges unless technically unavoidable and explicitly justified. Isolate any future privileged helper.
- Treat `nettop`, router responses, subprocess output, CSV, and other external/system data as untrusted. Validate schemas, ranges, identities, units, and parsing failures; fail closed on incompatible formats.
- Do not log secrets or user browsing information.

## Testing expectations

Every substantial implementation includes appropriate tests. Before considering a task complete, run the relevant configured checks:

- backend tests;
- frontend tests when applicable;
- Python/TypeScript type checking when configured;
- linting when configured;
- a production frontend build when frontend changes warrant it.

For measurement/accounting work, explicitly test normal monotonic counters, reset, restart, missing and duplicate samples, interface switching, zero traffic, large counters, and day/month/billing/timezone boundaries. Also test idempotency, gaps, overlapping scopes, and failure parsing external data when relevant.

Do not invent commands or introduce tooling solely to satisfy this checklist. Use the repository's configured commands and document any check that is not yet available.

## Workflow

For each task:

1. Inspect the existing implementation and relevant architecture.
2. Make the smallest coherent change.
3. Add or update tests.
4. Run relevant validation.
5. Fix failures caused by the change.
6. Summarize files changed.
7. Summarize tests/checks executed and their results.
8. State remaining limitations or unverified assumptions.

If an implementation decision conflicts with `docs/ARCHITECTURE.md`, stop and identify the conflict. Do not silently change, bypass, or reinterpret the architecture.
