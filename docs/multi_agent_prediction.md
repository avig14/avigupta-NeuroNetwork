# Multi-agent experiment: prediction (plan section 9)

Written: 2026-11-18 16:58:58 IST (IST wall clock), BEFORE any multi-agent code exists and BEFORE any run.
The experiment result file records the sha256 of this file, so the order is checkable.

## Setup being compared
- **v1 (single):** one orchestrator graph. Reliability, policy and security campaigns are
  parallel workers inside one graph. They share one state and are not isolated.
- **v2 (multi):** policy and security-adversary become independent sub-agents. Each has its
  own private state schema. They talk to the orchestrator only through validated JSON
  handoff contracts. A failed sub-agent is reported as a failed handoff, not a crash.
- Same frozen fleet, same policy, same k, same seeds.

## Plan's own prediction (section 9)
Multi-agent should help on wide audits (many tools, many scenarios) and cost far more.
If not, report that. An honest negative is a good result.

## Our specific predictions (written before running)
1. **Verdict accuracy:** no gain. v1 and v2 give the SAME verdict on at least 17 of 18 fleet
   agents. Reason: the campaigns are already independent and the graders are the same code.
2. **Cost:** v2 costs more. Wall time x1.05 to x1.5. JSON handoff volume is new overhead.
   Trials and tool calls: identical. Real LLM tokens are 0 in both (no LLM), so the
   "15x tokens" claim cannot be tested here. We report handoff bytes as a crude proxy only.
3. **Latency:** no speed-up. Campaigns already run in parallel in v1.
4. **Error amplification:** v2 is safer under a crashing sub-agent ONLY because we chose
   to fail closed (a failed handoff blocks SHIP). v1 crashes the whole audit. This is a
   design effect, not a property of multi-agent in general. We will say so.
5. **Lost-context incidents:** v2 adds a new failure class (a contract field missing or
   invalid). We expect 0 on healthy runs and more than 0 under injected faults.
6. **Wide audits:** we CANNOT test the plan's main claim well. Our fleet is narrow (4
   tools, about 66 trials). We will run one padded "wide" variant and label it a toy.

## What would change our mind
If v2 shows a different verdict on any fleet agent, we read that trace by hand and report it.
