# ADR-002 — External-effect safety over automatic retry

Status: Accepted

An external-effect action is only confirmed when adapter-visible evidence proves its postcondition. A crash, timeout, or browser loss after a possible effect but before confirmation becomes `outcome_unknown`. The engine does not infer absence and does not automatically retry.
