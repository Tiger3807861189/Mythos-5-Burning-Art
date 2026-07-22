1. **Which approval architecture should the finished experience use?**
   - Why this matters: The choice determines implementation scope, migration strategy, compatibility, and which approval flow becomes authoritative.
   - Evidence or uncertainty: Implementing this approval flow is a substantive build; multiple approval concepts coexist, migration is incomplete, the feature flag is disabled, contradictory UX tests remain, and no mutation has occurred.
   - A. **Recommended option** — Unified UX with separate internals is recommended because it lowers migration risk while preserving a consistent experience.
   - B. Alternative — Complete the migration and retire legacy paths for the cleanest long-term model with the highest blast radius.
   - C. Alternative — Improve only the active flow for the smallest change while retaining fragmentation.
   - D. Promote the flagged flow after completing its unfinished migration work.
   - If unanswered: No safe default; work remains blocked until an independently reviewed plan can receive explicit approval.

2. **What rollout and compatibility policy should apply?**
   - Why this matters: Approval behavior can affect existing users, records, integrations, and rollback safety.
   - Evidence or uncertainty: The feature flag is disabled and migration work is incomplete; readiness and data compatibility are not established.
   - A. **Recommended option** — A staged rollout behind the flag is recommended because it validates migrated and legacy cases before expansion.
   - B. Alternative — Apply the new flow only to new records while legacy records retain current behavior.
   - C. Alternative — Perform one global migration and enablement for consistency with the highest operational risk.
   - D. Change presentation only and leave rollout and migration behavior untouched.
   - If unanswered: No safe default; work remains blocked without a rollout policy.

3. **Which UX contract should resolve the contradictory tests?**
   - Why this matters: The tests encode incompatible expectations, so implementation cannot infer the intended product behavior.
   - Evidence or uncertainty: It is unknown whether legacy behavior, current production behavior, or the migration-era design is authoritative.
   - A. **Recommended option** — Adopt one explicit state and failure contract, then update conflicting tests to it.
   - B. Alternative — Preserve current production behavior and treat conflicting tests as stale.
   - C. Alternative — Make the migration-era expectations authoritative despite compatibility risk.
   - D. Preserve the oldest tested contract and accept limited improvement.
   - If unanswered: No safe default; no production edit may begin.

MYTHOS_WAITING_FOR_HUMAN_V1