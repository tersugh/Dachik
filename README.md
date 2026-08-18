# Dachik

**Know where your data goes.**

Dachik is a privacy-first, local-first internet data usage sensor and ISP
accounting auditor. It independently measures network usage, tracks data plans
over their validity period, and compares observed usage with ISP-reported
balances to surface possible accounting discrepancies.

> Measure how much data is used — without monitoring what the user does online.

The macOS V1 is functional. It measures this Mac's audited network connection,
keeps evidence locally, and provides continuously available audits and exports.
It does not claim to detect fraud or guarantee that local measurements match an
ISP's billing boundary. Production packaging is still deferred; the current
LaunchAgent and browser workflow are development-oriented.

## What macOS V1 does today

- Measures real cumulative download and upload counters for one selected active
  macOS network interface.
- Runs the sensor independently of the browser, API, and terminal using a
  user-level LaunchAgent.
- Tracks a data plan for its validity period, including plans already partly used
  when Dachik starts.
- Preserves the original plan allowance, starting network balance, immutable
  provider balance checkpoints, and later balance updates as distinct evidence.
- Uses deterministic integer-byte accounting and restart-safe counter handling.
- Establishes new baselines after restarts, resets, interface changes, sleep, and
  unsafe gaps instead of inventing traffic.
- Uses a privacy-safe local connection identity so traffic is not silently
  attributed after the Mac switches to another connection on the same interface.
- Distinguishes trusted measured time, known non-attributable time, and unknown
  time while keeping the same plan audit active across measurement breaks.
- Provides point-in-time accounting, daily and hourly ledgers, exact event times,
  aligned provider-comparison windows, and deterministic measurement quality.
- Keeps current and historical audits available with local PDF, CSV, and JSON
  exports.

Provider comparisons are neutral. A numerical difference can be worth reviewing,
but it is not proof of fraud, theft, intent, or billing error.

## How measurement becomes an audit

```text
Operating-system counters
        ↓
raw observations
        ↓
continuity validation
        ↓
trusted usage intervals
        ↓
AuditEngine
        ↓
dashboard / audit / reports
```

macOS exposes cumulative counters. Dachik does not treat a cumulative value as
usage. It derives an exact integer-byte delta only between compatible consecutive
observations. When source, session, interface, connection identity, counter
direction, or timing continuity cannot be trusted, Dachik records the uncertainty
and starts from a safe new baseline.

The same authoritative `AuditEngine` supplies dashboard totals, detailed audits,
provider comparisons, and exports. Presentation differs; accounting does not.
Deep implementation details are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Accounting model

Dachik keeps these values separate:

- **Original plan allowance:** the data plan's full size.
- **Starting network balance:** what the provider reported remaining when Dachik
  began tracking.
- **Dachik-observed usage:** trusted traffic measured after tracking began.
- **Dachik-accounted remainder:** starting network balance minus trusted observed
  usage.
- **Latest provider-reported balance:** a later independent checkpoint, not a new
  Dachik baseline.

Example:

```text
Original plan allowance       30 GB
Starting network balance      23.91 GB
Dachik-observed usage          5.00 GB
Dachik-accounted remainder    18.91 GB
```

Dachik does not claim it measured the 6.09 GB used before tracking began. Later
provider balance updates never reset or rewrite the original 23.91 GB accounting
baseline. They create aligned comparison windows against trusted Dachik usage from
the same period.

## Continuous auditing and evidence quality

Audit continuity does not require counter continuity. The same plan audit can
remain active through sleep, shutdown, collector restarts, connection changes,
and temporary sensor failure. Trusted usage before and after a safe new baseline
continues accumulating against the original starting balance.

- **Measured:** Dachik has compatible, attributable counter evidence.
- **Known non-attributable:** Dachik can determine that the observed connection is
  not the connection assigned to this plan. It does not imply the ISP plan was
  unused elsewhere.
- **Unknown:** Dachik cannot determine what happened. Unknown time is never
  converted to zero usage.

Audit evidence coverage is:

```text
measured duration / (measured duration + unknown duration)
```

Known non-attributable duration is shown separately and does not by itself mean
sensor failure. Coverage maps deterministically to Excellent (95–100%), Good
(85–<95%), Limited (60–<85%), or Insufficient (<60%). It is not an AI confidence
score and does not imply whole-network coverage.

## Audit reports

**View audit** is available while a plan is active and after it becomes historical.
An audit includes:

- plan, original allowance, starting balance, latest reported balance, observed
  usage, and Dachik-accounted remainder;
- daily and hourly download/upload accounting;
- exact local-time connection, interruption, resumption, and balance events;
- immutable network balance checkpoints and aligned comparison windows;
- measured, known non-attributable, and unknown durations;
- evidence quality, methodology, measurement boundary, and limitations.

Exports are generated locally from the same audit state:

- **PDF:** readable report for a customer, support representative, or reviewer.
- **CSV:** structured UTC time-bucket evidence with integer-byte values.
- **JSON:** precise, timezone-aware, machine-readable deterministic audit state.

Reports summarize trusted intervals rather than dumping every raw counter sample.

## Privacy

Dachik records byte counters and the minimum metadata required for accounting,
continuity, and connection attribution. It does **not** collect or persist:

- packet payloads or protocol contents;
- URLs, DNS history, browsing history, or page titles;
- message, file, or application contents;
- traffic destinations or a history of sites and services used.

For Wi-Fi attribution, the network name and default gateway are used transiently
to derive an opaque local fingerprint. The network name is not persisted or
logged, and Wi-Fi identity is not exposed in reports.

V1 data, SQLite storage, logs, and generated evidence remain local. No Dachik
cloud account, telemetry service, remote database, or internet connection is
required for measurement and auditing.

## Measurement boundary

macOS V1 measures **this Mac's audited network connection**. It does not measure
every device sharing the same broadband or data plan. Traffic from phones, TVs,
tablets, other computers, and hotspot clients is not automatically included.

Router/gateway-wide measurement is a future `TrafficProvider`; it is not part of
the current macOS V1.

## Technology

Backend and accounting:

- Python 3.12
- FastAPI and Uvicorn
- SQLAlchemy 2.x
- SQLite with Alembic migrations
- ReportLab PDF generation

Frontend:

- React 19
- TypeScript 6
- Vite 7
- Vitest and ESLint

macOS measurement:

- macOS `netstat`, route, interface, and boot-session statistics
- privacy-safe local connection attribution
- user-level `launchd`/LaunchAgent background sensor

## Development setup

Prerequisites:

- macOS
- Python 3.12
- Node.js 20.19+, 22.13+, or 24+
- npm

Do not install Python packages globally. From the repository root:

```bash
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cd frontend
npm install
cp .env.example .env
```

`VITE_` variables are visible to the browser and must never contain secrets.

### Run the local application

Terminal 1, from the repository root:

```bash
source venv/bin/activate
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765 --reload
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). FastAPI remains bound to
loopback at `127.0.0.1:8765`.

### Background sensor

Activate the Python 3.12 virtual environment and run lifecycle commands from the
repository root:

```bash
python -m collector service install
python -m collector service start
python -m collector service stop
python -m collector service restart
python -m collector service status
python -m collector service uninstall
```

This development LaunchAgent references the current repository and virtual
environment. Moving or deleting either invalidates its configuration. A future
installer will manage production packaging.

For interactive debugging only:

```bash
python -m collector monitor
```

Do not run the manual collector and background service simultaneously. Optional
development flags include `--interval`, `--max-gap`, and `--interface` for
`monitor`; `service install` also accepts those configuration flags.

### Legacy development audit connection confirmation

An audit created before connection attribution is never rebound silently. While
connected to the audited network, confirm it explicitly and restart the sensor:

```bash
python -m collector connection confirm
python -m collector service restart
```

### Validation

From the repository root with the virtual environment active:

```bash
python -m pytest
python -m ruff check backend collector
python -m mypy backend collector
```

From `frontend/`:

```bash
npm test
npm run lint
npx tsc -b --pretty false
npm run build
```

## Repository structure

```text
collector/           macOS provider, monitor, accounting ingestion, service lifecycle
backend/app/         domain, repositories, deterministic audit engine, API, reports
backend/tests/       persistence, accounting, API, report, and lifecycle tests
frontend/src/        consumer tracking/audit UI and typed local API client
migrations/          reproducible SQLite schema revisions
docs/ARCHITECTURE.md authoritative architecture and measurement methodology
AGENTS.md            repository rules for coding agents
pyproject.toml       Python dependencies and development tooling
```

## Roadmap

macOS is the first reference implementation of a reusable measurement-provider
architecture. Future possibilities, none of which are implemented today, include:

- router/gateway measurement, beginning with an OpenWrt investigation;
- Android and Windows measurement providers;
- an iOS feasibility investigation;
- optional local-first synchronization;
- a future AI audit assistant.

Any future AI layer may explain and summarize deterministic Dachik evidence. It
must never replace the authoritative meter or independently calculate
authoritative byte totals, balances, timestamps, coverage, or discrepancy facts.

## Engineering philosophy

- Local-first by default and privacy by design.
- Missing data is unknown, never zero.
- Preserve raw evidence and derive accounting deterministically.
- Never blindly add measurements from different domains or boundaries.
- Report uncertainty instead of guessing.
- Keep deterministic systems authoritative for accounting.
- Keep complex engineering underneath a simple consumer experience.

## License

License information will be added before a wider public release.
