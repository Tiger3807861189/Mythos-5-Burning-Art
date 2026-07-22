1. **Which direction should govern the payment fix?**
   - Why this matters: The choice controls payment correctness and whether duplicate charges remain preventable.
   - Evidence or uncertainty: The prescribed approach contradicts evidence because retries already caused duplicate writes, while the uniqueness constraint is the final integrity boundary; transaction details and the available idempotent mechanism remain unknown.
   - A. **Recommended option** — Preserve the constraint and design an idempotent retry flow after diagnosing transient failure classes.
   - B. Alternative — Preserve the constraint and suspend payment-write retries pending diagnosis.
   - C. Alternative — Preserve the constraint and produce a remediation plan without production changes.
   - D. Remove the constraint and amplify the demonstrated duplicate-write risk.
   - If unanswered: Make no changes and retain the uniqueness constraint.

MYTHOS_WAITING_FOR_HUMAN_V1