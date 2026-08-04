# Chrome Extension Bug Audit and Fix Plan

Date: 2026-08-02  
Scope: `extension/` and its Native Messaging boundary in `native_host.py`  
Review mode: static inspection plus existing build/lint/test commands; no production code changed

## Executive summary

The production build succeeds, but the extension is not ready for a reliability-focused release. The most urgent defect is shared initial-state mutation: findings from one scan can remain in later scans. The next priority is the Native Messaging contract, where TypeScript and Python disagree about event shapes and the real failure message is discarded. Storage operations can also fail while reporting success, and generated HTML reports are not fully self-contained or safely constrained at the runtime trust boundary.

Recommended order:

1. Fix scan-state isolation and add regression tests.
2. Normalize and validate the Native Messaging protocol.
3. Make port teardown session-aware and error-safe.
4. Make history persistence observable and quota-aware.
5. Harden and test HTML report generation.
6. Address smaller UI state and quality-gate defects.

## Verification baseline

| Check | Result | Notes |
| --- | --- | --- |
| `npm run build` | Pass | TypeScript project build and Vite production bundle completed. |
| `npm run lint` | Fail | 3 errors and 1 warning; details are in EXT-009. |
| `pytest -q test/unit/test_native_host.py` | Blocked | The active Python environment does not have the declared dev dependency `responses`. |
| `npm audit --omit=dev` | Blocked | The configured `npmmirror.com` registry does not implement the npm audit endpoint. No dependency-security conclusion can be drawn. |
| Extension-specific automated tests | Missing | `extension/package.json` has no `test` script or test dependencies. |

## Prioritized findings

| ID | Priority | Area | Finding | Status |
| --- | --- | --- | --- | --- |
| EXT-001 | Critical | State | Scan findings mutate the shared initial-state array and can leak into later scans. | Confirmed |
| EXT-002 | High | Protocol | Python event envelopes disagree with `NativeResponse`, and scan failures lose their real error message. | Confirmed |
| EXT-003 | High | Lifecycle | Error paths leak the native port; retry teardown can race with the newly connected port. | Confirmed conditional path |
| EXT-004 | High | Storage | Chrome storage failures resolve as success; count-only retention does not guarantee quota safety. | Confirmed |
| EXT-005 | High | Report security | Exported HTML executes remote code and interpolates some unvalidated fields into markup/URLs. | Confirmed hardening defect |
| EXT-006 | Medium | Messaging/UI | Start, stop, and retry commands use optimistic UI but ignore runtime/background failures. | Confirmed |
| EXT-007 | Medium | Data contract | Python has `references: List[str]`, but the extension expects one `reference` and the host sends neither. | Confirmed |
| EXT-008 | Low | Options UI | A selected finding can remain visible after filters remove it from the table. | Confirmed |
| EXT-009 | Medium | Quality gate | The committed lint command currently fails. | Confirmed |

## Detailed repair plans

### EXT-001 — Shared scan findings survive reset

Evidence:

- `extension/src/types/scan.ts` exports one object whose `findings` member is one mutable array.
- `extension/src/background/background.ts:11` and `:155` shallow-copy that object, preserving the array reference.
- `extension/src/background/background.ts:56` pushes findings into that shared array.
- A later start shallow-copies the already-mutated array again. History objects can also temporarily retain the same array reference.

User impact:

- A second scan can display and export findings from the first scan.
- `summary.totalFindings` can disagree with `findings.length`.
- Deduplication resets do not help because old array entries are already present.

Implementation plan:

1. Replace the exported mutable object as the reset mechanism with `createInitialScanState(): ScanState` that creates fresh arrays on every call.
2. Stop mutating `currentScanState.findings` in place; append with a new array or move transitions into a pure reducer.
3. Snapshot findings when constructing a history record.
4. Use the same factory in `useScan` for local reset operations.
5. Add a regression test that performs two scans in one background-worker lifetime.

Acceptance criteria:

- Scan B starts with zero findings after Scan A found at least one issue.
- Scan A's saved history remains unchanged while Scan B receives events.
- `INITIAL_SCAN_STATE` or its replacement cannot be mutated by a scan transition.

### EXT-002 — Native event contract drift and lost errors

Evidence:

- `extension/src/lib/nativeMessaging.ts` requires every `NativeResponse` to contain `status`.
- `native_host.py:197-225` and `:264-278` emit progress, finding, completion, and failure events without `status`.
- `native_host.py:275-278` puts a scan failure in top-level `error`.
- `extension/src/background/background.ts:87-90` reads `data.error`, so an actual scanner exception is displayed as `Scan stopped`.
- The casts at `background.ts:44`, `:49`, and `:64` bypass validation at the process boundary.

Implementation plan:

1. Define one versioned, discriminated protocol shared as fixtures between Python and TypeScript. Every envelope should have `status`, `action`, and a documented `data` shape; errors should use one location.
2. Update every Python emitter and immediate action response to follow that envelope.
3. Replace `NativeResponse` plus unchecked casts with an action-discriminated union and runtime parsing/validation.
4. Treat malformed events as protocol errors: preserve the last valid state, close the affected session, and surface an actionable message.
5. Add Python serialization tests and TypeScript fixture-consumer tests for every action.

Acceptance criteria:

- A scanner exception containing `boom` results in the UI showing `boom`.
- Missing or malformed `scan_completed.summary` cannot create a `completed` state or a corrupt history item.
- Python-generated fixtures type-check and parse in the extension without `as unknown as` casts.

### EXT-003 — Native port leak and cross-session disconnect race

Evidence:

- `extension/src/background/background.ts:25-30` marks a response error but does not disconnect or clear the port.
- A retry disconnects the old port at `:163`, then assigns a new port at `:164-167`.
- The old port's asynchronous disconnect callback uses the global handler and unconditionally clears `nativePort` at `:112`; it can also mark the new `validating` scan as failed at `:107-110`.

Implementation plan:

1. Introduce a scan session identifier and capture the concrete port in its callbacks.
2. Centralize teardown in an idempotent `closeSession(session, reason)` function.
3. Ignore message/disconnect events whose session is no longer active.
4. Close and clear the active port on every terminal response, including `status: error` and malformed data.
5. Test error → immediate retry, stop → immediate retry, and stale late-event scenarios with fake ports.

Acceptance criteria:

- Disconnecting an old port cannot null or fail the current session.
- Every terminal path removes listeners/port references exactly once.
- A retry after native-host rejection reaches `scanning` and completes normally.

### EXT-004 — Storage reports false success

Evidence:

- `extension/src/lib/storage.ts:14-20`, `:31-33`, `:42-44`, and `:51-53` never inspect `chrome.runtime.lastError`.
- The background catch at `background.ts:81-83` therefore cannot observe common asynchronous storage failures.
- `MAX_HISTORY_ITEMS` limits record count, not encoded byte size; one or several large evidence fields can still exceed the storage quota.

Implementation plan:

1. Wrap Chrome callbacks in one helper that rejects when `runtime.lastError` is set.
2. Version and validate persisted history data before returning it to UI components.
3. Enforce retention by serialized size as well as count, evicting oldest records before a bounded retry.
4. Decide how to handle a single record larger than the budget: truncate explicitly marked evidence, decline persistence with a visible warning, or store a reduced summary. Do not silently alter evidence.
5. Listen for storage changes in the options page so open history views remain current.

Acceptance criteria:

- A mocked quota error rejects `saveScanHistory` and reaches the background error path.
- Retention never loops indefinitely and always removes oldest records first.
- Corrupt or old storage data does not crash `HistoryList` or `ScanDetail`.

### EXT-005 — Exported HTML is not a safe, self-contained artifact

Evidence:

- `extension/src/lib/report-template.ts:64` loads and executes `https://cdn.tailwindcss.com` whenever a downloaded report is opened; the report is unstyled offline and depends on mutable remote code.
- `report-template.ts:28` inserts `finding.severity.toLowerCase()` into an HTML attribute without escaping or whitelisting.
- `report-template.ts:40` inserts `cvssScore` without runtime numeric validation/escaping.
- `report-template.ts:51` accepts any reference URL scheme. HTML escaping does not make an unsafe URL scheme safe.
- These values cross a native-process/storage boundary without runtime validation (EXT-002/004).

Implementation plan:

1. Generate a fully self-contained report with a small inlined stylesheet; remove all remote scripts.
2. Map severity through an explicit allowlist instead of deriving a class from input.
3. Validate numeric fields and escape their formatted strings.
4. Allow only intended reference schemes (normally `https:` and optionally `http:`); render other values as plain text.
5. Add `rel="noopener noreferrer"` to external links.
6. Add hostile-fixture tests for every interpolated field and a snapshot/assertion that the report contains no external script or stylesheet dependency.

Acceptance criteria:

- A report renders with networking disabled.
- Hostile severity, score, URL, evidence, title, and reference fixtures cannot create elements, attributes, scripts, or executable links.
- The output contains no remote `<script>` and no unexpected network dependency.

### EXT-006 — Optimistic commands ignore failures

Evidence:

- `extension/src/hooks/useScan.ts:46-59` changes local state before `start_scan`/`stop_scan` is accepted and supplies no response callback.
- `checkInstallation` at `:62-71` does not inspect `chrome.runtime.lastError`.
- The background trusts `message.payload` at `background.ts:150` and reports start success immediately after posting, before native acceptance.

Implementation plan:

1. Add typed request/response helpers that convert both `runtime.lastError` and `{ success: false }` into rejected promises.
2. Let background state broadcasts be authoritative; use only a short-lived local `submitting` state if immediate feedback is needed.
3. Validate target URL and plugin identifiers again in the background worker.
4. Separate native connection, native acceptance, scanning, cancelling, cancelled, and failed states where the UI needs different behavior.

Acceptance criteria:

- Background rejection or runtime unavailability never leaves the popup indefinitely in `validating`.
- Invalid payloads do not reach the native host.
- The user receives the actual failure reason and can retry.

### EXT-007 — Finding references are dropped

Evidence:

- The Python `Finding` model defines `references: List[str]`.
- The TypeScript `Finding` model defines `reference?: string`.
- `native_host.py:209-225` sends neither `references` nor `reference`.
- Options and exported reports only render the singular TypeScript property.

Implementation plan:

1. Standardize on `references: string[]` across Python events, TypeScript types, storage, options, and reports.
2. Add a migration/normalizer that converts old singular `reference` values to a one-item array.
3. Apply safe-URL handling from EXT-005 to every reference.

Acceptance criteria:

- All references from a Python finding appear in live/saved data and exports.
- Old stored records with `reference` still load.

### EXT-008 — Filtered table can show stale details

Evidence:

- `FindingTable` stores a full selected object at `extension/src/options/components/FindingTable.tsx:13`.
- The detail panel at `:68` is independent of whether that finding still exists in the current filtered `findings` prop.

Implementation plan:

1. Store only the selected finding ID.
2. Derive the selected object from the current `findings` prop, or clear selection when the ID is absent.
3. Use the same stable finding-key helper used by deduplication.

Acceptance criteria:

- Changing search/severity filters cannot display a detail that is absent from the visible result set.

### EXT-009 — Lint quality gate fails

Evidence from `npm run lint`:

- `src/components/ui/badge.tsx:52`: `react-refresh/only-export-components`.
- `src/components/ui/button.tsx:58`: `react-refresh/only-export-components`.
- `src/popup/PopupApp.tsx:120`: synchronous state update inside an effect.
- `src/popup/PopupApp.tsx:143`: missing `url` dependency warning.

Implementation plan:

1. Move exported variant helpers/constants out of component modules, or narrowly configure the refresh rule for generated UI primitives with justification.
2. Model smoothed progress as a dedicated hook whose reset does not require the flagged effect pattern.
3. Make active-tab URL initialization an explicit mount-only callback without closing over changing form state, or include the intended dependency and guard against overwriting user input.
4. Make `npm run lint` a required CI check.

Acceptance criteria:

- `npm run lint` exits successfully with zero warnings.
- Progress reset and user-edited URL behavior have regression tests.

## Design risks requiring a decision

These are not all proven user-visible failures, but they should be resolved while touching the adjacent code:

- Cancellation: `native_host.py:342-352` does not cooperatively cancel the scanner. The extension currently posts `stop_scan` and immediately disconnects, effectively coupling cancellation to transport/process lifetime. Decide whether cancel means cooperative scanner cancellation, process termination, or only UI detachment, and expose a `cancelling/cancelled` outcome.
- Service-worker persistence: scan state exists only in module memory. Decide whether reopening the popup after a worker restart should restore the active/last scan from `chrome.storage.session` or show history.
- Summary integrity: derive or validate counts against findings before display/persistence. `native_host.py:259` also hardcodes `totalUrlsScanned` to zero.
- Permission scope: evaluate replacing broad `tabs` access with `activeTab` if the only requirement is pre-filling the current HTTP(S) URL.
- History freshness: an options page opened before scan completion does not subscribe to new history records.

## Regression test matrix

| Layer | Required cases |
| --- | --- |
| State reducer/factory | fresh arrays; two sequential scans; duplicate event; stale session event; terminal transitions |
| Protocol parser | every action; missing fields; wrong severity; top-level native error; unknown protocol version |
| Background with fake Chrome APIs | connect failure; error then retry; stop then retry; stale disconnect; storage rejection |
| Storage | empty/corrupt/legacy data; lastError; byte retention; oversized single record; delete/clear errors |
| Report generator | normal snapshot; hostile strings; unsafe URL schemes; offline/no remote resources |
| React UI | command rejection; active-tab prefill without overwriting edits; progress reset; filter selection clearing |
| Python host | exact envelopes for start/progress/finding/completed/failed/stopped and reference mapping |

## Definition of done

- EXT-001 through EXT-007 are fixed with automated regression coverage.
- EXT-008 and EXT-009 are resolved or explicitly deferred with an issue owner.
- `npm run lint`, `npm run build`, extension tests, and native-host protocol tests pass in a documented clean environment.
- A manual unpacked-extension smoke test covers install detection, scan, live findings, completion, export, history, stop, and immediate retry.
- No release artifact depends on the current developer machine, a remote report script, or silent Chrome API failures.
