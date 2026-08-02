# Chrome Extension Refactoring Roadmap

Date: 2026-08-02  
Companion audit: `docs/extension-bug-fix-plan.md`

## Goal

Refactor the extension so scan behavior is deterministic, the Python/TypeScript boundary is explicit and validated, persistence failures are visible, report export is safe and offline-capable, and UI components can be tested without a live Chrome installation.

This roadmap intentionally starts with characterization tests and high-risk bug fixes. Visual cleanup comes after the state and protocol boundaries are stable.

## Target module boundaries

| Boundary | Responsibility | Proposed location |
| --- | --- | --- |
| Domain | Scan/finding types, fresh-state factory, pure transitions, summary invariants | `src/domain/scan.ts`, `src/domain/scanReducer.ts` |
| Protocol | Versioned request/event unions, runtime decoders, Python fixture contract | `src/protocol/native.ts` |
| Background orchestration | One active session, port identity, command validation, broadcast/persistence effects | `src/background/scanController.ts` |
| Chrome adapters | Promise wrappers for runtime, native messaging, tabs, and storage APIs | `src/platform/chrome/` |
| Persistence | Versioned history repository, migration, retention policy | `src/history/historyRepository.ts` |
| Reporting | Pure report model normalization and self-contained HTML/JSON serializers | `src/reporting/` |
| Popup UI | Thin state consumer composed from focused screen components | `src/popup/components/` |
| Options UI | History query state, filtering, selection, and presentation | `src/options/` |

Dependency direction should remain UI/background → application/domain → platform interfaces. Domain and reporting code must not import `chrome` or React.

## Phase 0 — Establish a safety net

Deliverables:

1. Add an extension test runner (Vitest is a natural fit for the existing Vite stack), DOM environment, and a typed fake for the Chrome APIs used here.
2. Add `test`, `test:watch`, and `typecheck` scripts; make lint, typecheck, test, and build separate CI steps.
3. Capture current Python Native Messaging outputs as fixtures, including the existing failure mismatch, before changing the contract.
4. Add characterization tests for report output, storage callbacks, and two sequential scans.
5. Document the Python dev-environment setup so `responses` and the native-host tests are installed consistently.

Exit criteria:

- Tests can run without Chrome or a real native host.
- At least one failing regression test exists for EXT-001, EXT-002, EXT-004, and EXT-005 before their fixes.

## Phase 1 — Stabilize domain state and protocol

Deliverables:

1. Introduce `createInitialScanState()` and a pure scan reducer. No exported reset object may contain mutable shared collections.
2. Model commands/events as discriminated unions rather than `action: string` plus `Record<string, unknown>`.
3. Add a protocol version and runtime decoder at the native boundary.
4. Normalize `references`, severity, timestamps, optional values, and error placement.
5. Introduce an explicit `scanSessionId`; every event and callback must be associated with the active session.
6. Replace background globals spread across the service-worker file with a small `ScanController` owning state, deduplication, and port lifecycle.

Suggested transition model:

`idle → connecting → scanning → completed | failed`  
`scanning → cancelling → cancelled`  
`failed | completed | cancelled → connecting` for retry/new scan

Keep installation availability separate from scan status if possible; `hostAvailability: unknown | available | unavailable` avoids treating setup state as a scan result.

Exit criteria:

- Sequential scans and stale native events are deterministic.
- Native fixtures parse without unchecked casts.
- Every terminal state closes exactly its own session.

## Phase 2 — Make platform effects reliable

Deliverables:

1. Wrap callback-style Chrome APIs once and reject on `chrome.runtime.lastError`.
2. Move storage behind a history repository with schema versioning and normalization.
3. Implement count-and-byte retention with a documented oversized-record policy.
4. Persist only immutable scan snapshots.
5. Subscribe the options page to `chrome.storage.onChanged`.
6. Decide and implement scan-state recovery across Manifest V3 service-worker restarts, preferably through `chrome.storage.session` if active-state recovery is a product requirement.
7. Replace fire-and-forget popup commands with typed command results while keeping the background controller authoritative.

Exit criteria:

- Chrome API failures are visible to callers and users.
- Storage migrations and quota paths are covered by tests.
- Worker restart behavior is documented and manually verified.

## Phase 3 — Isolate reporting and harden exports

Deliverables:

1. Normalize a `ReportModel` before serialization; do not interpolate raw protocol/storage objects.
2. Replace Tailwind CDN usage with minimal inlined report CSS.
3. Add centralized HTML escaping, severity allowlisting, numeric formatting, and safe-link handling.
4. Keep JSON export deterministic and consider including a report/schema version.
5. Move browser download mechanics behind a small adapter so serializers remain pure and unit-testable.

Exit criteria:

- Reports render offline and contain no remote executable resources.
- Hostile fixtures cannot create executable markup or links.
- HTML and JSON reports are generated from the same normalized data model.

## Phase 4 — Decompose the popup and options UI

`PopupApp.tsx` is currently about 733 lines and combines styling, Chrome tab discovery, progress animation, command submission, setup instructions, result calculations, finding lists, and export orchestration.

Proposed popup components/hooks:

- `PopupShell` and `StatusChip`
- `TargetForm`
- `PluginSelector`
- `InstallationHelp`
- `ScanProgress`
- `LiveFindingList`
- `ScanResultSummary`
- `FindingAccordion`
- `ExportActions`
- `useActiveTabUrl`
- `useSmoothedProgress`

Refactoring rules:

1. Keep server/background state out of duplicated component state unless the value is truly local UI state.
2. Move severity metadata and finding-key generation into domain utilities used by popup and options.
3. Replace index keys with stable finding keys.
4. Prefer class-based style tokens or small focused style modules over hundreds of inline object literals and event-time DOM style mutations.
5. Preserve keyboard focus, visible focus states, labels, and reduced-motion behavior during visual extraction.
6. Store selected finding IDs, not copied finding objects, and derive selection from the current filtered data.

Exit criteria:

- `PopupApp` is an orchestration component rather than the implementation of every screen.
- Each major screen can be rendered in isolation with fixture state.
- `npm run lint` passes with zero warnings and no broad rule disablement.

## Phase 5 — Cancellation, permissions, and observability

Deliverables:

1. Add cooperative cancellation to the scanner if feasible; otherwise document and deliberately implement process termination semantics.
2. Ensure `stop_scan` acknowledgement, timeout, and forced teardown have distinct observable paths.
3. Evaluate `activeTab` versus `tabs` and retain only required extension permissions.
4. Remove unconditional/local-machine debug side effects from native-host startup and use a configurable, bounded logging policy.
5. Add structured development logs keyed by scan session without persisting target secrets or evidence unnecessarily.
6. Make `totalUrlsScanned` real or omit it until supported instead of hardcoding a misleading zero.

Exit criteria:

- Cancel has one documented meaning and a tested state transition.
- Manifest permissions have written justification.
- Logs are useful for session diagnosis without becoming an unbounded or sensitive-data store.

## Suggested pull-request sequence

Keep each change reviewable and avoid mixing UI redesign with protocol migration:

1. Test harness and Chrome fakes.
2. Fresh-state factory plus EXT-001 regression fix.
3. Protocol v1, Python emitters, fixtures, and reference mapping.
4. Session-aware background controller and command error handling.
5. Storage adapter, schema migration, and retention behavior.
6. Self-contained report model/generator.
7. Popup hook extraction and component decomposition.
8. Options selection/history freshness cleanup.
9. Cooperative cancellation and permission review.

Each pull request should leave build, lint, and tests green. During protocol migration, support either an atomic extension/host release or a short compatibility decoder so users cannot install mismatched halves.

## Non-goals

- Redesigning the scanner plugin engine before the extension boundary is stable.
- Changing vulnerability-detection behavior as part of UI refactoring.
- Adding the placeholder global-settings features.
- Replacing the entire UI component library solely to resolve two Fast Refresh lint errors.

## Completion checklist

- [ ] No shared mutable reset state.
- [ ] Versioned protocol with runtime validation and cross-language fixtures.
- [ ] Session-aware, idempotent native-port lifecycle.
- [ ] Observable Chrome API/storage errors and tested retention.
- [ ] Offline, hardened report export.
- [ ] Popup and options modules split by responsibility.
- [ ] Cooperative or explicitly forced cancellation semantics.
- [ ] Least-privilege manifest review completed.
- [ ] Lint, typecheck, extension tests, native-host tests, and production build pass.
- [ ] Manual unpacked-extension smoke test documented and passed.
