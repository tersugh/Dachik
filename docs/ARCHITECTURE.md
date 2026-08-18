# Dachik Phase 1 Architecture

## Purpose and principles

Dachik is a privacy-first application that independently measures internet data consumption. It helps users understand locally observed usage and compare it with ISP-reported bundle consumption without treating a discrepancy as proof of ISP fraud.

Phase 1 ships a local-first macOS MVP (V1) while keeping the measurement and storage contracts reusable for gateway/router collection (V2). macOS, OpenWrt, and future gateways are `TrafficProvider` implementations that produce the same standardized cumulative byte-counter observations for one accounting engine. Prefer byte counters and operational metadata. Do not capture raw packet payloads or browsing content in the MVP.

## Release boundaries

### V1: local macOS collector

In scope:

- total upload/download for the Mac, with interface and time-window scope;
- best-effort per-process/application attribution where macOS exposes it;
- durable historical samples and rollups;
- configurable bundle allowance and billing-cycle tracking;
- daily and monthly analytics;
- manual, timestamped ISP balance snapshots;
- discrepancy calculation and exportable evidence reports.

Out of scope:

- other devices on the LAN, ISP account scraping, cloud accounts/sync, remote administration, packet payload inspection, URL/domain history, and claims that a discrepancy establishes wrongdoing.

### V2: gateway/router monitoring

In scope after V1:

- total WAN upload/download across the monitored network;
- per-device attribution when the gateway exposes reliable counters;
- ISP-reported consumption ingestion (manual first, provider integration later);
- the same comparison, limitation, and reporting model as V1.

V2 is an extension through collector adapters, not a rewrite. Router support is capability-based: a router may provide WAN totals only, totals plus device counters, or neither reliably. Cross-device application attribution is not promised.

## Technology and logical components

- **Collector — Python 3.12:** schedules observations, invokes a `TrafficProvider`, normalizes cumulative counters, derives restart-safe deltas, and writes samples through the service layer.
- **`MacOSTrafficProvider`:** an interface-counter adapter for measured totals, supplemented by `nettop` for best-effort process attribution. It publishes its scope, source, units, monotonicity, and health.
- **`GatewayTrafficProvider` (V2):** the extensible gateway contract, first implemented for OpenWrt. Later adapters may use standards or vendor APIs, but all emit the same normalized observation contract.
- **Measurement engine:** validates samples, detects discontinuities, calculates deltas, prevents double counting, assigns confidence/coverage flags, and produces time-bucket rollups.
- **FastAPI service:** local API for measurements, applications, bundle configuration, ISP snapshots, analytics, health, and report generation. Business rules live behind the API rather than in React.
- **SQLite repository:** the only V1 application database and the source of truth for configuration, cumulative observations, accepted deltas, attribution, snapshots, rollups, and audit metadata. Keep boundaries sufficiently clean for optional future cloud work, without building a remote persistence layer now.
- **React + TypeScript + Vite UI:** browser-delivered local dashboard, history, Data Audit Experiment workflow, bundle state, snapshot entry, methodology/health display, and report export. Use a small chart library selected during implementation; charts must preserve missing intervals rather than visually interpolating them as measurements.
- **Report generator:** creates machine-readable and human-readable exports containing source, period, methodology, arithmetic, coverage gaps, resets, exclusions, and limitations.

Python 3.12 is fixed for Phase 1. Pin Node.js and TypeScript versions in repository tool files before frontend implementation; they are not selected by this architecture. PostgreSQL, cloud accounts, cloud sync, and remote databases are not required for the initial public release and must not be implemented in V1.

## Deployment model

V1 is a single-user, local-first macOS installation:

1. A long-running collector starts at user login (initially a per-user `launchd` agent).
2. FastAPI listens only on localhost/loopback and is not exposed to the LAN.
3. FastAPI serves the React + TypeScript + Vite frontend locally, and Dachik opens it in the user's normal web browser.
4. SQLite and exports live in the user's Application Support directory with user-only permissions.
5. Collection continues without an internet connection. There is no cloud dependency or telemetry by default.

Electron, Tauri, and other native desktop shells are explicitly excluded from the MVP. Native packaging may be reconsidered after the measurement product is proven.

Avoid running the entire application as root. If validated measurement coverage later requires privilege, isolate it in a minimal signed helper with a narrow IPC contract; the API, UI, database, and report generator remain unprivileged. V2 can run either on the user's Mac polling a router or as a small gateway agent. The normalized ingestion contract remains transport-independent.

## First usable product

The first usable release follows this path:

```text
Mac network interface
  → cumulative RX/TX counters
  → Python collector
  → deterministic delta/accounting engine
  → SQLite
  → FastAPI localhost API
  → React dashboard in the user's browser
```

This vertical slice is the immediate development priority. The dashboard should eventually expose plan allowance, locally measured usage, estimated remaining allowance, download versus upload, daily usage, projected exhaustion date, best-effort top applications, ISP-reported remaining balance, observed discrepancy, and measurement coverage. This section defines the product target; it does not require all dashboard capabilities to be built at once.

## Development-phase rule

Architecture is not implementation authorization. Implement only functionality assigned to the current development phase. A future or deferred capability must not be implemented merely because this document describes a path for it.

In particular, do not prematurely implement cloud accounts/sync, PostgreSQL, Network Extensions, native desktop shells, advanced router integrations, IPFIX/NetFlow, cryptographic report signing, ISP portal automation, or other deferred infrastructure. The immediate objective is to prove that Dachik accurately and reliably measures real internet usage.

## V1 data flow

```text
macOS interface counters ----> total-counter adapter ---+
                                                       |
nettop process counters -----> attribution adapter -----+--> validation/reset detection
                                                              |
manual ISP entry -----------> FastAPI -------------------------+--> SQLite
                                                              |
React UI <------------------ FastAPI <--- analytics/reporting -+
```

At each interval, the collector records raw **counter values** (not packet contents), wall-clock and monotonic timestamps, boot/session identity, source, interface, and adapter version. The measurement engine converts valid consecutive cumulative observations into delta intervals. Rollups are derived from accepted intervals and can be rebuilt.

The API stores a manual ISP snapshot exactly as reported by the user: timestamp, remaining balance or provider-reported consumption, unit, bundle/cycle, optional note, and provenance `manual`. It never converts that value into a local measurement.

## Data Audit Experiment

`Data Audit Experiment` is the user-facing unit of work for an independent comparison. It presents a simple workflow:

```text
Start Data Audit
  → enter ISP and bundle
  → begin independent measurement
  → periodically enter ISP balance
  → compare measurements
  → generate report
```

An experiment logically groups the ISP/provider, data plan or bundle, starting allowance, measurement start/end, billing-cycle information, local byte measurements, ISP balance snapshots, measurement coverage, observed discrepancies, and final audit report. This is an aggregate/workflow concept, not a requirement to denormalize storage: bundles, observations, intervals, snapshots, and reports remain normalized and are associated with an experiment identifier.

## Byte-accounting methodology

### Counter domains

Every value belongs to an explicit domain:

- `measured.interface`: bytes observed on selected external macOS interfaces;
- `attributed.process`: best-effort bytes associated with a process/application;
- `measured.gateway_wan`: bytes observed at the router's WAN boundary (V2);
- `attributed.device`: best-effort bytes associated with a LAN device (V2);
- `reported.isp`: a balance or consumption value reported by the ISP/user.

Never add values from different domains. Store bytes as non-negative 64-bit integers. Use decimal GB (1 GB = 1,000,000,000 bytes) for ISP-facing comparison unless the provider documents another unit; UI and reports must state the conversion. Preserve original ISP units and entered values.

### Totals and attribution

For V1, cumulative inbound/outbound counters on active external interfaces are the authoritative local total. Exclude loopback. Classify VPN/tunnel, hotspot, AWDL, virtual-machine, and other virtual interfaces explicitly; do not blindly sum every interface because encapsulation can double-count the same traffic. The initial policy selects the internet egress interface(s), records policy changes, and marks ambiguous intervals.

`nettop` supports CSV logging, external-interface filtering, delta output, and per-process summaries on macOS. It is a provisional attribution source, not a stable application API. Its output must be tested on each supported macOS version. Process-attributed totals can omit short-lived processes, privileged/system traffic, traffic observed before collector startup, or traffic macOS groups differently. They may also differ in protocol-layer overhead. Therefore:

- never invent or proportionally allocate unattributed bytes;
- show `unattributed = authoritative total - reconciled attributed bytes` only when scopes and intervals match;
- if attributed bytes exceed the authoritative total, mark the interval unreconciled instead of clamping or rewriting it;
- do not sum per-process data into the authoritative total.

### Deltas, restarts, and resets

For consecutive observations with the same source, counter identity, boot/session, and scope:

```text
delta = current_counter - previous_counter, when current_counter >= previous_counter
```

If the counter decreases, the boot/session changes, the interface disappears, the source changes, or the gap exceeds the configured continuity threshold, close the prior segment. Treat the first value in the new segment as a baseline with zero attributable delta—never as usage since zero. Record a discontinuity reason and expose the resulting coverage gap.

Audit continuity does not require counter continuity. A bundle experiment remains active across sleep, shutdown, collector restarts, connection changes, and sensor failures. Trustworthy intervals before and after a break accumulate against the experiment's original immutable starting-balance evidence; a new OS baseline never resets that audit balance. Higher-level audit periods are derived from accepted `UsageInterval` evidence and classified discontinuities rather than stored as mutable balances. Periods distinguish measured time, deterministically known non-attributable time, and unknown time. Unknown time is never usage of zero.

V1 measures one explicitly selected current data plan on this Mac at a time. Current measurement targeting is separate from experiment lifecycle: switching the target does not complete, cancel, or rewrite another valid audit. A singleton selection identifies the current target. With no selection, exactly one active compatible audit may be used deterministically; multiple active audits are an explicit conflict and must never be resolved by timestamp order.

The physical interface name alone is not sufficient connection identity: the same `en0` may carry unrelated Wi-Fi networks. V1 persists only an opaque hash of privacy-safe local connection identity evidence and binds an experiment to that source. A clearly different or unidentifiable connection is not attributed to the plan. This describes only the local Mac measurement boundary and does not prove whether the ISP bundle was used elsewhere.

Persist observations before deriving rollups, make ingestion idempotent with a source/session/sequence key, and commit each interval atomically. After a Dachik restart, continue only from a compatible persisted baseline. Do not bridge sleep, shutdown, or collection gaps without evidence that the underlying cumulative counter remained continuous. Wall-clock time defines reporting buckets; monotonic time detects elapsed intervals and clock changes. Split an interval crossing a day or billing boundary only with an explicitly documented allocation rule; otherwise keep it in its observed interval and flag boundary uncertainty.

### ISP comparison

Local measured usage and ISP-reported usage remain separate series. For two compatible ISP snapshots:

```text
ISP consumption = earlier remaining balance - later remaining balance
discrepancy bytes = ISP consumption - locally measured usage
discrepancy % = discrepancy bytes / ISP consumption * 100
```

If snapshots report cumulative consumption, use its positive change instead. Do not calculate when units, bundle identity, cycle, timestamps, or direction are incompatible. Every displayed discrepancy and report must show the formula, values, units, selected local boundary, interval overlap, exclusions, and data coverage. Possible causes include ISP accounting boundaries, protocol overhead, rounding, delayed updates, zero-rated traffic, tethered/other devices, VPN behavior, counter gaps, or configuration error. A discrepancy alone must never be labelled fraud, theft, or overbilling. When the values agree within the declared tolerance and coverage is adequate, Dachik should say that the ISP accounting broadly matches the independent measurement instead of searching for wrongdoing.

### Measurement coverage and confidence

Coverage describes how much of the ISP/local comparison interval Dachik observed reliably; it is not a probability that either party's number is correct. For the initial model:

```text
coverage % = reliably observed duration within the comparison interval
             / total comparison-interval duration × 100
```

Only accepted, continuous intervals from the selected authoritative counter series count as reliably observed. Time outside the experiment, collector downtime, incompatible source/scope changes, unresolved resets, excessive sampling gaps, and ambiguous interface periods remain explicit coverage gaps. Overlapping samples count once. Missing intervals are never zero usage and Dachik must not extrapolate them into measured bytes.

The current V1 percentage is specifically accepted measured duration divided by eligible tracking duration. Known non-attributable and unknown durations are exposed separately and neither is counted as measured. This duration ratio is evidence coverage, not a confidence score and not proof of zero bundle use outside the local measurement boundary.

Initial user-facing categories are:

- **Excellent:** 95–100%
- **Good:** 85–<95%
- **Limited:** 60–<85%
- **Insufficient:** <60%

Thresholds are configurable and the threshold version belongs in the report methodology. Coverage is calculated for the exact comparison interval and direction/scope being reported. A large discrepancy with poor coverage must not be presented as strong evidence. When coverage is Insufficient, the UI and report must state: **“Insufficient evidence for a meaningful comparison.”** The raw values may remain visible with their provenance, but no strong comparison conclusion may be drawn. Reports preserve every discontinuity and gap used in the calculation.

## Storage model

Use normalized entities with migrations:

- `sources` and `source_capabilities`;
- `counter_series` (domain, direction, interface/device/process identity, unit, scope);
- immutable `counter_observations`;
- derived `usage_intervals` (delta, start/end, quality, discontinuity);
- `applications` and time-bucketed `application_usage` with privacy-safe identities;
- `bundles` and billing cycles;
- immutable `isp_snapshots` plus explicit corrections rather than silent edits;
- rebuildable daily/monthly `rollups`;
- `collector_runs`, health events, schema/methodology versions, and report manifests.
- `data_audit_experiments` linking the normalized plan, time window, measurements, snapshots, coverage result, discrepancies, and reports.

SQLite is the only V1 application database. It uses WAL mode, foreign keys, bounded transactions, and one logical writer. Store timestamps in UTC plus the billing timezone. Reports pin a methodology version so later algorithm changes do not silently alter prior evidence; recalculation creates a new report/version. Repository/service boundaries may support a future cloud architecture, but V1 contains no PostgreSQL driver, remote database, account, or sync path.

## Security and privacy model

- Collect counters and the minimum metadata required for attribution and diagnostics. Do not collect packet payloads, URLs, DNS history, page titles, or browsing content in the MVP.
- Process identity should be limited to stable application identifiers where available (for example bundle ID), display name, and optional executable identity needed to merge process lifetimes. Do not retain command-line arguments or full user-specific paths.
- Keep data local by default. No analytics, cloud upload, or ISP credential storage in V1.
- Bind the API to `127.0.0.1`/`::1`; reject non-local origins, use a per-install secret for state-changing API requests, and do not log that secret.
- Store sensitive tokens in macOS Keychain if future router/ISP integrations need them. Secrets, `.env` files, signing material, databases, and user exports must never enter Git.
- Apply least privilege, user-only filesystem permissions, dependency pinning, signed/notarized release artifacts, and log redaction. Logs contain health and aggregate IDs, not browsing content.
- Exports are user-initiated and warn that device/application names and usage patterns may be sensitive. Provide configurable retention and deletion.

Threats considered include a malicious local webpage reaching the loopback API, another local user reading data, a compromised router returning false counters, tampered snapshots, dependency compromise, and accidental sensitive logging. Source provenance and validation reduce—but cannot eliminate—these risks.

## Measurement limitations

- Interface counters measure bytes at a particular network layer and may include headers/retransmissions that an ISP counts differently.
- Local V1 cannot see traffic from other household devices, router-originated traffic, or usage while the Mac/collector is off.
- VPNs, Private Relay, virtual interfaces, tethering, multi-path transfers, sleep, interface handoff, and counter resets can change visibility or cause double-counting if misclassified.
- Per-process attribution is best effort and will not necessarily reconcile with interface totals.
- Manual ISP balances may be rounded, delayed, cached, direction-agnostic, or based on an undocumented billing boundary.
- V2 router counters differ by firmware and may reset on reboot, wrap at limited width, omit hardware-offloaded traffic, include LAN/management traffic, or lack stable device identity. MAC randomization and IPv6 privacy addresses complicate device attribution.
- Neither V1 nor V2 proves ISP intent or fraud. Reports must include the supported interval, coverage percentage, discontinuities, data sources, methodology version, and all relevant limitations.

The UI must represent missing data as missing—not zero—and label estimates or allocations distinctly. No traffic measurement may be fabricated for demos, gaps, or tests; synthetic fixtures must be visibly marked synthetic and never enter user reports.

## macOS measurement and permissions

Phase 1 investigation order:

1. Read cumulative interface byte counters through documented system statistics exposed by Darwin (`getifaddrs`/interface data) or a narrowly wrapped native bridge; validate against `netstat -ib` and controlled transfers.
2. Use `/usr/bin/nettop` logging/CSV mode for best-effort per-process byte attribution. Parse by column name, not position, and fail closed on schema changes.
3. If either source is insufficient on supported macOS versions, investigate a signed native Network Extension system extension as a later, separately approved capability. Do not misuse a packet-tunnel provider as a general traffic interceptor.

Baseline interface counters are expected to work without elevated privilege, but actual coverage and `nettop` visibility must be verified across supported macOS versions, standard/admin accounts, system processes, VPNs, and sleep/wake. Do not request Full Disk Access: this design has no need to read user files. Do not request Accessibility or Screen Recording.

A Network Extension fallback would require Apple signing, the Network Extensions capability/entitlement, a system extension installation approval flow, and native Swift/Objective-C glue outside the Python collector. Apple documents content filters as system extensions on macOS and restricts the data provider sandbox to protect network content. Such an extension is not part of V1 until a spike proves it necessary and privacy review approves its metadata-only design.

## V2 router integration strategies

OpenWrt is the first concrete `GatewayTrafficProvider` target. V2 should first prove reliable gateway-level WAN accounting—and then per-device accounting where reliable—on OpenWrt before pursuing broad router compatibility. Probe and record capabilities before enabling an adapter.

The first implementation should investigate OpenWrt `ubus`/`rpcd`, native interface counters, and `nftables` counters, selecting the smallest reliable metadata-only approach for explicit WAN totals. A later OpenWrt agent remains an option if polling cannot provide correct reset/offload behavior.

The general gateway architecture remains extensible, but these are later strategies rather than V2-first-release commitments:

- **Standards-based counters:** SNMPv3 IF-MIB 64-bit WAN counters (`ifHCInOctets`/`ifHCOutOctets`) for totals. Require encrypted/authenticated SNMPv3; avoid SNMPv1/v2c across untrusted networks.
- **Vendor APIs:** versioned adapters for documented router/controller APIs, with credentials in Keychain and read-only scopes.
- **Flow export:** IPFIX/NetFlow/sFlow metadata for device attribution where supported. Configure sampling awareness and never export payloads.
- **Other router platforms and gateway mode:** adapters or an on-path Dachik agent, subject to platform-specific firewall/offload validation.

Router web-page scraping and packet capture are not default strategies. If metadata-only header accounting is ever required, it needs a separate threat model, explicit consent, retention limits, and architecture approval; payload bytes must not be retained.

For each router, validate counter width, layer, directions, WAN membership, reset behavior, hardware offload, bridge/VLAN behavior, polling limits, and timebase. Stable device aliases are local user annotations; never infer a person from a device identifier.

## Testing plan

Every substantial feature includes tests. The initial test pyramid is:

- **Unit:** counter normalization, reset/wrap/restart handling, interface classification, idempotency, unit conversion, billing cycles, timezone/DST boundaries, discrepancy formulas, and limitation generation.
- **Property-based:** arbitrary monotonic/resetting counter sequences never produce negative usage, fabricated gap usage, overflow, or duplicate totals.
- **Contract:** recorded `nettop` outputs from every supported macOS version; router capability fixtures; API schemas; report manifests; database migrations and repository behavior. PostgreSQL compatibility is deferred and is not a V1 test requirement.
- **Integration:** collector → SQLite → API → rollup/report, crash recovery at each transaction boundary, concurrent reads, clock changes, sleep/wake, process/PID reuse, and manual snapshot corrections.
- **System measurement:** controlled uploads/downloads with known byte ranges across Wi-Fi, Ethernet, VPN, interface handoff, and restart/reset scenarios. Compare multiple independent system counters and publish tolerances; never tune fixtures to force agreement.
- **Privacy/security:** assert payloads, URLs, DNS queries, command lines, credentials, and secrets never enter the database/logs/reports; test loopback binding, origin/auth controls, file permissions, retention deletion, and malicious adapter input.
- **UI/report:** missing-data rendering, accessibility, large histories, methodology display, arithmetic reproducibility, provenance labels, and mandatory limitation text.

Release gates require supported-macOS measurement matrices, documented tolerances, zero unexplained negative/double-counted intervals, migration/backup recovery tests, and reproducible report calculations. Synthetic test data must be isolated and labelled.

## Architecture decisions deferred until implementation review

- minimum supported macOS version and eventual native packaging approach (post-MVP only);
- exact Darwin counter bridge and whether `nettop` provides acceptable coverage;
- Node.js, TypeScript, charting library, and package manager versions;
- sampling interval, continuity threshold, default retention, and rollup policy;
- evidence-report formats and signing/tamper-evidence requirements;
- first supported OpenWrt version and polling transport.

## References

- Local macOS manual pages: `man nettop`, `man netstat`
- [Apple: Network Extension](https://developer.apple.com/documentation/networkextension)
- [Apple: Content filter providers](https://developer.apple.com/documentation/networkextension/content-filter-providers)
- [Apple: Network Extensions Entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.networkextension)
- [Apple TN3120: Expected use cases for packet tunnel providers](https://developer.apple.com/documentation/technotes/tn3120-expected-use-cases-for-network-extension-packet-tunnel-providers)
- [Apple TN3134: Network Extension provider deployment](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment)
