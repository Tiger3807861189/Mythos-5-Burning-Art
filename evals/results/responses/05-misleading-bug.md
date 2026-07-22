1. **What should the UI promise after a save request is accepted but before queued processing is confirmed?**
   - Why this matters: The answer defines whether delayed or stale reads represent failure, pending work, or acceptable optimistic success.
   - Evidence or uncertainty: A toast-only patch is not an established root cause; queue processing is delayed, reads can be stale, an unrelated toast regression exists, and investigation must precede any patch.
   - A. **Recommended option** — Pending until confirmed is recommended, with Saving or Queued followed by Saved only after confirmation.
   - B. Alternative — Optimistic success reports Saved at queue acceptance and notifies only on later failure.
   - C. Alternative — A regression-only patch fixes the unrelated toast issue while preserving queue and read behavior.
   - D. Immediate confirmation treats a missing follow-up read as failure despite known stale reads.
   - If unanswered: No safe default; make no mutation until the user-visible save contract is chosen.

MYTHOS_WAITING_FOR_HUMAN_V1