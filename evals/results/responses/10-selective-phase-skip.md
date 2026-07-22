1. **What compatibility policy should the exported method rename follow?**
   - Why this matters: The request to skip discovery would hide a public-compatibility change and could break consumers outside the repository.
   - Evidence or uncertainty: The exported method is used by generated clients and an external compatibility test; phase 1 INTAKE is active, phases 2 through 13 remain pending, and downstream migration permission is unknown.
   - A. **Recommended option** — Preserve compatibility by adding the new name, retaining a deprecated forwarding alias, and updating callers.
   - B. Alternative — Perform an intentional breaking rename with a breaking-change release and migration guidance.
   - C. Alternative — Rename only the implementation while keeping the exported API unchanged.
   - D. Defer the rename until downstream ownership and timing are established.
   - If unanswered: Choose A because it is reversible, protects existing consumers, and makes no production mutation before the complete lifecycle.

MYTHOS_WAITING_FOR_HUMAN_V1