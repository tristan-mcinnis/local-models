# State flow review

Reviewed against server/serve.py, server/commands.py, server/backends/,
cli/local-model, and menubar/LocalModelsBar sources. This is a design review,
not a runtime state store. The live registry and backend probes remain the
sources of operational truth. Tests use fake backends on a real HTTP daemon.

## Warm commands: selected improvement

Unattempted (`warm_operation: null`) → queued → running → succeeded or failed.
Retry from any state creates a new attempt and clears the previous error.
The daemon's lock-protected WarmAttempts owns the latest command record;
BackendUse owns activity and idle clocks; backend status owns residency.

A caller can issue a blocking warm (existing result/error response) or a
non-blocking warm (accepted reply with operation_id). Polling models exposes
the attempt, status counts queued work as busy and summarizes idle failures. Choices
show Queued, Warming, or a failure reason. Users can retry the same model after fixing its
backend or weights. No new command was added to the house manifest.

A running command may target an already warm model. A failed warm may have
loaded weights before its first inference failed. Succeeded plus cold is
valid after unload or a later model switch. A failure must not silently
become Idle, and an older worker must not overwrite a newer attempt.
All terminal paths record outcomes before releasing use claims, including
backend construction and worker-start failure. Backend errors retain the
existing HTTP error envelope. Unexpected warm startup errors become 502.

Disconnect leaves accepted work running. Cancellation is unsupported.
Daemon interruption loses workers and records; an operation id is meaningful
only within that daemon lifetime. Concurrent requests remain permitted:
latest-request outcome wins, not latest-completion. Superseded attempts
cannot be individually queried. This bounded record avoids a persistent job
system but cannot promise durable receipt or complete history.

Verification: tests/test_commands.py checks running/success, failure/retry,
request disconnection, claim cleanup, startup failure, stale completion,
polling detail and existing synchronous contracts. Idle sweeper tests cover
protection against unloading active work.

## Follow-up: backend ownership

The next review reproduced two backend instances from concurrent first access,
violating the daemon's one-owner-per-backend contract. Construction now holds
one cache lock across lookup, creation and publication. Backend constructors
only configure objects; model loading, status probes, inference and unload
remain outside this lock. Failure or interruption releases the lock and leaves
no cache entry, so later access retries normally. Tests in
`tests/test_backend_cache.py` reproduce the old duplicate-owner race and check
shared ownership, distinct backend names, failure and interruption recovery.

This makes existing per-instance lifecycle locks effective for all callers;
it does not serialize different-model inference or change forced unload.
The trade-off is that first construction briefly serializes cache access
across backend names. The shipped constructors do not perform network I/O or
load models. No live model race or process failure was induced for validation.

## Request scheduling and panel recovery

A model lease now spans prepare plus complete inference, warm, or stream relay.
Different-model requests on one backend queue until the active model's work
finishes. Same-model requests can overlap, and independent backends do not
block one another. A queued switch takes precedence over later requests for
the old model, preventing starvation. Exceptions and disconnected streams
release their lease. `BackendUse` claims cover requests waiting for model
leases, so the idle sweeper cannot tear down pending work.

For `wait:false`, the request records a queued attempt and starts a worker
without waiting for unload, model access or backend construction. The request
reserves its activity claim before acknowledgement. The worker waits for any
existing unload, acquires a model lease, then marks running and records its
terminal outcome before releasing the reserved claim. Polling distinguishes queued from running.
Malformed warm results fail with the existing 502 envelope rather than
recording false success. Blocking warm retains its response shape.

The panel now owns an explicit local idle/running/failed action state with
operation kind and model. Admission is guarded before suspension. HTTP error
and hint text stay visible through refresh until retry. Transport failure or
cancelled waiting reports an unknown outcome and asks for refresh, because
losing a connection does not cancel work already accepted by the daemon.
Warming and Unloading have separate progress labels. Panel state is not the
source of daemon residency or a cancellation mechanism.

Verification: `tests/test_model_leases.py` exercises inference and stream
switch exclusion, same-model overlap, other-backend independence, failure
cleanup and interrupted queue recovery. `tests/test_commands.py` exercises
real HTTP admission behind unload/model leases, queued/running/success/failure,
slow backend construction and malformed returns. Swift operation tests use
injected transport for success, daemon errors, timeout, cancellation, duplicate
input and retry; offscreen proofs cover error and unload presentation.

Model leases protect calls through the daemon. Callers using backend ports
directly bypass them. Explicit unload's existing force-after-drain policy
remains supported; it can still interrupt work after the drain timeout.

## Other important flows

| Flow | States, transition and source | Visibility and actions | Failure, interruption, concurrency and verification |
| --- | --- | --- | --- |
| Inference / streaming | Claimed → prepare → generate/relay → release; BackendUse and backend own state | API text, SSE or error; caller may retry | Finally releases claims after errors/disconnect. A model lease now prevents different-model replacement through the daemon for the whole generation/stream. Same-model requests may overlap. Backend owner construction is now atomic; concurrent first access shares one instance and failed construction permits retry. Backend and relay tests cover ordinary paths, not every cross-model race. |
| Idle unload | Warm → unused threshold → exclusive unload → cold; BackendUse clocks and live registry threshold | Models expose idle seconds, basis and activity; next inference reloads | Active claims prevent idle unload. Failed unload can retry next sweep. Polling does not count as use. tests/test_idle_unload.py covers clocks, claims and recovery. |
| Explicit unload | Requested → bounded drain → unload → response; backend owns actual residency | Existing unload response or HTTP error | Existing force behavior after drain timeout can unload without a granted claim. A running warm is not cancelled by unload. Kept for compatibility; needs a separate concurrency decision. |
| Registry / downloads | Download → register on disk → validated hot reload; models.json owns registration | CLI reports download/validation errors; list/status show accepted registry | Interrupted pull can leave unregistered files. Invalid registry edits retain last good snapshot. Existing backend instances retain endpoint configuration, so registry changes do not imply backend reconfiguration. Registry tests and network roundtrip_pull.py verify separate portions. |
| Panel refresh / selection | Checking → snapshot or unreachable → refresh; daemon owns data, panel owns selection | Rows, warm labels, Return/command-Return actions, Refresh | Refresh errors clear rows and may mislabel decode failures as daemon down. Overlapping refreshes can apply out of order. Swift tests cover polling/backoff and model rendering. |
| Panel warm / unload | Idle/failed → running(operation, model) → idle/failed; panel owns command presentation | Warming/Unloading, retained error/hint and retry through the model row | Admission guard prevents overlapping panel commands. Timeout/cancellation reports unknown outcome. Error survives refresh and clears on retry. Swift injected-transport tests cover normal, failure and recovery. |
| Daemon toggle | launchctl request → delay → health refresh; launchd and HTTP own actual state | Toggle and reachable status | Pending/error states are not explicit; rapid toggles may race. No app was opened during this review. |

Authentication is intentionally absent on the loopback-only daemon. There is
no web navigation or form submission flow. External services enter mainly
through Hugging Face downloads and runtime backend processes; no new auth,
network service or dependency is introduced by the warm outcome change.
