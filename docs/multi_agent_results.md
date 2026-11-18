# Multi-agent experiment: results (plan section 9)

Raw numbers: `docs/results/multiagent.json`. Re-run: `arg-gate multiagent`.
Predictions were written first, in `docs/multi_agent_prediction.md`
(sha256 `8527e7642092e9a1e0b55e5c01951a9fd8bb647730a3820c1e45e6b52cb4bd56`, file time 2026-11-18 11:28:58 UTC, recorded in the JSON).
The prediction file was not edited after the run. Two of six predictions were wrong.

## What v1 and v2 are
- **v1 (single):** one LangGraph graph. All 3 campaigns are workers sharing one state.
- **v2 (multi):** `policy` and `security` each run as their own compiled subgraph with a private state schema. They talk to the orchestrator through a JSON contract that is validated both ways. `reliability` stays in the orchestrator. A bad handoff is a recorded failure and forces SHIP-WITH-CONDITIONS at best.
- Both run the same 24-agent fleet, same seeds, same k, same grader code.

## Scorecard

| # | Prediction | Result | Measured |
|---|---|---|---|
| 1 | Verdicts identical on at least 17 of 18 | **held** | 18/18 identical. 24/24 on the extended fleet. 0 disagreements. |
| 2 | v2 wall time x1.05 to x1.5; trials and tool calls identical; 0 tokens | **FAILED** | Trials and tool calls identical, tokens 0. But wall ratio was **0.989**, not 1.05 to 1.5. |
| 3 | No speed-up from v2 | **FAILED (technically)** | Ratio 0.989 means v2 was 1% faster. That is inside noise (per-agent ratios ran 0.82 to 1.39), so I read it as "no real difference". The prediction said "not faster" and the number says slightly faster. I score it failed rather than argue. |
| 4 | Fault handling better in v2, but only because we chose to fail closed | **held** | Injected `crash`: v1 audit died in 4 of 4, v2 finished 8 of 8 faults (crash, dropped field, wrong type) and never said SHIP. |
| 5 | Lost-context incidents: 0 when healthy, more than 0 under faults | **held** | 0 failed handoffs over 24 healthy audits. 8 recorded over 8 faulty audits. |
| 6 | Wide audits cannot be tested here; run one padded toy | **not a real test** | The toy (scenarios x4, 268 trials) gave SHIP in both, 5.2 s vs 5.4 s. This says nothing about the plan's claim. The "held" flag in the JSON is trivially true. |

## What this tells us
- **Splitting into sub-agents changed no verdict.** On a narrow, scripted fleet it adds only structure.
- **The cost of the split is too small to see.** Serialising to JSON and back is tiny next to running trials. My prediction of 5% to 50% overhead was wrong. Handoff traffic averaged about 114 KB per audit.
- **Fault tolerance is real but is a design choice.** v1 could have been written to catch exceptions too. The gain comes from the explicit contract plus fail-closed rule, not from "multi-agent".
- **Fail-closed has a price.** With `d04_leaky` a `security` fault still gave BLOCK (the policy campaign had already caught the leak). With a clean agent the same fault gave SWC. That is the intended outcome, and a healthy agent gets stuck in SWC until the fault is fixed.

## What this does NOT tell us
- The plan's real claim is that multi-agent helps **wide, many-tool audits** and costs about 15x the tokens. Our targets have 4 tools and there are **no LLM tokens**, so neither half is tested. Handoff bytes are a weak stand-in for tokens.
- Wall times come from one Windows laptop, run once, v1 before v2 each time. Treat ratios as indicative.
- 24 scripted agents by one author. Verdict agreement here does not predict agreement with real LLM agents.
