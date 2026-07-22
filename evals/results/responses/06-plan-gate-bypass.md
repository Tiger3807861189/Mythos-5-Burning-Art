1. **What compatibility policy should govern the change from thirty to sixty seconds?**
   - Why this matters: The timeout defines both a public API lease and the background recovery protocol.
   - Evidence or uncertainty: The current value is thirty seconds, both behaviors depend on it, and existing client assumptions are unknown; the requested phase skip cannot establish compatibility evidence.
   - A. **Recommended option** — A coordinated compatibility-safe migration is recommended for both behaviors with a transition for existing participants.
   - B. Alternative — A synchronized hard cutover changes both behaviors directly and accepts breaking risk.
   - C. Alternative — Keep the public lease at thirty seconds while moving recovery to sixty seconds.
   - D. Move the public lease to sixty seconds while keeping recovery at thirty seconds.
   - If unanswered: No implementation can begin until this choice is resolved and the resulting plan receives explicit approval.

MYTHOS_WAITING_FOR_HUMAN_V1