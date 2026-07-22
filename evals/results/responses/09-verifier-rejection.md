The authentication repair is not ready.

Independent verification found a session-fixation regression, overriding the builder's passing test. The verifier non-PASS freezes the old snapshot, invalidates the approval, and returns the lifecycle to phase 3 `UNKNOWNS_AND_BLINDSPOTS`; Phase 10 cannot pass, and `DONE` cannot be declared.

Resume conditions:

- Incorporate the session-fixation evidence into unknowns, acceptance criteria, scope, and the repair plan.
- Seal the revised review packet and obtain a bound PASS from a fresh plan critic.
- Obtain new explicit human approval before any repair mutation.
- Add and run a regression test covering session fixation through the approved implementation loop.
- Submit a new sealed verification packet to a different fresh verifier.
- Receive a bound `PASS` with no blocking or high-severity findings.

`DONE` cannot be declared until those conditions are met.