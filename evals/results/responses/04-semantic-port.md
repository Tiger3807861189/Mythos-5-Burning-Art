1. **What should preserve behavior mean when Rust semantics conflict with conventional TypeScript behavior?**
   - Why this matters: The choice defines the public contract for Unicode handling, error precedence, streaming across chunk boundaries, and integer overflow.
   - Evidence or uncertainty: The source deliberately contains subtle behavior in all four classes; a source-to-target semantics map is required, while permission to preserve quirks or allow documented deviations is unknown.
   - A. **Recommended option** — Exact behavioral compatibility is recommended, including results, error ordering, streaming state, overflow, and observable quirks.
   - B. Alternative — Preserve exact behavior except for a small explicitly approved exception list.
   - C. Alternative — Prefer idiomatic TypeScript strings, numbers, errors, and streams while accepting compatibility differences.
   - D. Provide strict-compatible and idiomatic modes at the cost of API and test complexity.
   - If unanswered: No safe default; the human gate remains closed before discovery, planning, or implementation.

MYTHOS_WAITING_FOR_HUMAN_V1