# TODO / Status: Agent Release Gate (prototype v0.1)

Source of truth: `Year 2 Outclass/plan.md` (v2). Section numbers below point at it.
Last updated: 18 Nov 2026, ~17:30 IST (freeze 19:00 IST). Git: last pushed `a23f903`. Everything below marked NEW is **uncommitted** (waiting for "commit it"). Only pushed commits count at the freeze.

## Update 17:30 IST (final re-verification pass)
- pytest: **50 passed**.
- `arg-gate meta` (24-agent fleet): pooled recall 19/19 (Wilson 0.83-1.00); false-SHIP 0/19; false-BLOCK 0/5; hold-out 6/6, 0 false-BLOCK on 2 clean. Frozen hold-out hashes verified at run time. d09 and h06 give SWC, not BLOCK (they still are not SHIP).
- Meta-eval C mutation score: 5/5 mutants killed, control agent SHIP.
- Layer ablation: without L0c -> 1 newly missed (d13); without L0 -> 6 newly missed; without L1 -> 3 newly missed (d06, d09, h06). Nothing newly wrongly blocked.
- Red team (`docs/redteam_log.md`): round 1 evaded 18/23, round 3 evaded 0/22, 0 false positives. Holes found and fixed. Known gaps listed there.
- Multi-agent experiment (`docs/multi_agent_results.md`): 4 of 6 predictions held, 2 failed (v2 was not slower: ratio 0.989). Verdicts identical 24/24. v2 fails closed under injected faults; v1 crashed 4/4.
- Docs added: `docs/architecture.md` (diagram, framework matrix, target contract, privacy, cost, non-goals).
- Report now carries an automation disclosure and lists soft findings.
- LLM layer built (18 Nov, see `docs/llm_layer.md`): L3 judge, real LLM baseline, judge red-team. Still needs humans or more time: B calibration (50 labels, kappa), LangSmith, targets #2 and #3, RAG, bigger hold-out, AgentDojo payloads, customer discovery.
- Still needs the user: enable GitHub Actions, record demo, review `team.json`, commit timing.


## Legend
`[x]` done and verified  `[~]` done but weak / partial  `[ ]` not done  `[!]` blocked / needs a human

---
## 1. Human-only steps (cannot be done by Claude)
- [!] Fill the registration Google Form: https://forms.gle/ZJUYKwTYjsMsVB2b9 (deadline was 3:30 PM). Tell organizers the fork name differs from `buildathon-<team-name>`.
- [!] Review `team.json`. Values are **provisional**: team name = "Agent Release Gate", members' `name` = their GitHub login (real names unknown). The CI check needs no `CHANGE_ME`.
- [!] Decide commit timing. Rules say first commit after genesis = `team.json`, then commit+push every 30-60 min. User said: no commit, no push until told. **Risk: one big late commit looks bad to the tracker.**
- [!] Record the demo (track `ai-agents` must show an agent actually using the tool). Not recorded.

## 2. Build status by plan section
### Sandbox and target interface (5.1, 6.3, 6.9)
- [x] Mock retail MCP server: FastMCP 4.2.1, SQLite, 4 tools (`get_order`, `issue_refund`, `update_address`, `send_email`), every call logged.
- [x] In-process transport and real Streamable-HTTP transport (subprocess). Same verdicts on both (checked on one target).
- [x] Per-trial reset from `clean.db`; diff taken PRE (after seeding) to POST. Second reset verified on Windows.
- [x] Target contract: task channel (`Task`) + tool channel (`Tools` over MCP).
- [x] Trust boundary: refuses targets outside `./fleet` unless `--trust-target` (tested).
- [x] Timeout + one retry per trial; persistent crash is recorded, not raised (tested).
- [~] Only ONE target app (retail). Plan floor says 3 base agents (Retail, DB Admin, Email). Not built.

### Trust ladder (6.4)
- [x] L0 deterministic: state diff, canary, policy-as-code (refund cap, scope, exfil, deletion, state corruption).
- [x] L0c claim-vs-state: **regex extraction** (plan says LLM extraction; no key). Code verifies against the diff.
- [x] L1: pass^k + Wilson CI. Plan numbers (n=6 to 73) checked in tests.
- [ ] L2 trajectory checks (plan marks later).
- [x] L3 LLM judge (soft-only, untrusted-data wrapper, error != pass). Meta-eval B (human calibration) still NOT done: no human labels.
- [x] Skeptic: **deterministic** replay + evidence check (plan says LLM skeptic).
- [x] L4 human gate via LangGraph `interrupt()` + `Command(resume=...)` (tested: accept / reject / defer).

### Orchestrator and campaigns (6.2, 6.3, 6.5)
- [x] ONE LangGraph graph: profile, plan, Send fan-out (3 campaigns), aggregate, skeptic, synthesize, human_gate, finalize.
- [x] Two-tier CI: smoke (k=1, L0+L0c, skips skeptic and adversary) and full (k=5, adversary, skeptic).
- [x] Cost cap `--max-trials`.
- [x] Adaptive adversary: **deterministic escalation + mutation** (plan says LLM adversary). Reaches the subtle hold-out bug after naive payloads fail (tested).
- [~] Payload library: 10 **team-written** payloads. Plan says import 10 AgentDojo payloads. Not done (custom-attack path unverified, plan 8.2 E).
- [x] Verdict rules + `VALIDITY_NOTE` on every verdict. Exit codes 0 SHIP / 1 BLOCK / 2 SWC [MINE] / 3 usage.
- [x] Policy file with prose clauses; findings cite the clause (grounding).

### Report (7 Step 7)
- [x] `evidence.json` (full) + `report.html` (verdict, state diff, tool trace, clause, adversary log, cost).
- [ ] Replay CLI (`arg-gate replay <evidence.json>`). Today replay = rerun scenario id + seed by hand.
- [ ] CI example (GitHub Action snippet using the exit code).

### Meta-evals (8)
- [x] Fleet: 13 dev defects + 3 clean; 6 hold-out defects + 2 clean (24 agents; 19 defects + 5 clean). Hashes in `fleet/manifest.json`, verified at run time.
- [x] A seeded-defect fleet (recall, precision, false-SHIP, false-BLOCK, Wilson CIs, dev / hold-out / pooled).
- [x] D skeptic ON vs OFF + evidence faithfulness.
- [x] F self-consistency (3 audits per agent).
- [x] G health: from our own records (plan says LangSmith; not used).
- [x] I deltas vs Baseline 1 (**text-only heuristic stand-in, NOT an LLM judge**).
- [x] Layer ablation: L0c off.
- [ ] B judge calibration (needs LLM judge + 50 human labels).
- [x] C mutation score: 5/5 (5 mutants only; small).
- [x] Layer ablations: L0c, L0, L1 off; skeptic off via D.
- [ ] Fleet reaching >= 35 defect instances (have 19). 24-case floor: 19 defects + 5 clean = 24 total, but plan wants 6 clean (have 5) and hold-out wants ~4 clean (have 2). Not fully met.

### Tests and docs
- [x] pytest: 50 pass (incl. red-team regressions, contract validation, v1/v2 fail-closed, mutation).
- [ ] README "Your project" section (rules say keep it current).
- [ ] LangSmith tracing (plan 6.x). Not wired. No key.

## 3. Honest deviations from plan.md (must be said in the demo)
1. **Core gate has no LLM.** Fleet agents, adversary, L0c extractor, skeptic are deterministic code. LLM parts (L3, real baseline) were added 18 Nov and tested on SMALL samples only. The judge prompt was tuned on dev agents; hold-out was not used for tuning. The fleet agents are scripts, so judge-family bias on real LLM targets is untested.
2. Scripted-agent results test the **plumbing**. They are NOT evidence the gate catches defects in real LLM agents.
3. Fleet builder = grader author = same person. Hold-out is biased in the gate's favour (plan 8.5 wants different people). The hold-out was frozen before the first hold-out run, but after the scenarios and graders existed.
4. F (flip rate) and D (skeptic delta) are ~0 by construction (deterministic agents). Weak evidence.
5. Wilson intervals are wide (hold-out has 6 defects: 0 misses only bounds false-SHIP below ~39%). Variants of one defect are correlated.
6. Thresholds (pass^k < 0.5 BLOCK, exit code 2) are [MINE] and uncalibrated.
7. Payloads are team-written, not AgentDojo.
8. One defect (D09, wrong refund amount) was invisible to the first scenario set. A partial-refund scenario (R7) was added after seeing this. That is dev tuning, logged here.

## 4. Next (priority order)
1. User says "commit it": commit in small logical commits (team.json first, per rules). Then wait for "push".
2. README "Your project" section + 60-second demo script.
3. Replay CLI + CI example.
4. Third-party or real-LLM target agent so the demo shows a real agent using the tool.
5. LLM judge + B calibration if a key appears.

---
## 5. Plan conformance audit (plan.md v2, line by line) , verified 18 Nov 2026 ~16:50 IST
Build-bearing sections are 5, 6, 7, 8, 9, 10, 12 (P0a to P3). Sections 0-4, 11, 13-17 are research/notes: nothing to build.

### P0a (plan 12) , DONE
| Plan item | Status | Proof |
|---|---|---|
| Pinned FastMCP/LangGraph, env | DONE | `fastmcp==4.2.1`, `langgraph==1.2.22` in pyproject; installed = same (checked) |
| Retail MCP server, 4 tools | DONE | `sandbox/retail_server.py`: get_order, issue_refund, update_address, send_email |
| Seeded bug: refund > $500 no approval | DONE | `fleet/dev/d01_no_cap.py` -> BLOCK, policy_refund_cap |
| Seeded bug: canary leak | DONE | `fleet/dev/d04_leaky.py` -> BLOCK, canary_leak |
| One scripted run gives a state diff | DONE | evidence.json `trials[].diff`, report.html diff table |
| Measure DB copy time | DONE | reset_db median 0.48 ms, p95 1.82 ms, max 15 ms (n=200, tiny seed DB; NOT the plan's unverified "<2 ms" claim for real sizes) |
| Measure cost per audit | PARTIAL | 1.75 s, 66 trials, 97 tool calls per full audit; 0 LLM tokens/dollars (no LLM) |

### P0b: orchestrator , MOSTLY DONE
| Plan item | Status | Proof |
|---|---|---|
| LangGraph: profile, plan, campaigns, executor, L0/L1, skeptic, interrupt, verdict | DONE | `orchestrator/graph.py`; end-to-end runs |
| L3 in the graph | DONE (opt-in) | `--l3`; soft findings only |
| L0 SQLite diff + canary scanner | DONE | graders/l0.py |
| Target interface contract (5.1) | PARTIAL | task channel = Python `Task` object, NOT an OpenAI-compatible chat endpoint; tool channel = MCP (in-memory + Streamable HTTP). No stdio. |
| Framework matrix (Step 2) | NOT DONE | document only |
| Workflow diagram | NOT DONE | document only |

### P1a: intelligence, tools, retrieval , PARTIAL
| Plan item | Status | Proof |
|---|---|---|
| Adversary agent, adaptive multi-turn | PARTIAL | deterministic escalation + mutation (`campaigns/adversary.py`), NOT an LLM. Test shows it skips ignored naive payloads and breaches h01 |
| RAG over policy docs + OWASP + MAST | NOT DONE | `Policy.retrieve` is a dict lookup by clause id. No OWASP/MAST corpus |
| Grounding check: verdict cites policy clause | DONE | `policy_clauses_cited` in verdict; shown in report.html |
| L0c claim checker | DONE (regex) | extraction is regex, not LLM. Test: correct state + false message -> SHIP with L0c off, BLOCK with L0c on |
| Target #2 (DB admin) | NOT DONE | |

### P1b: parallel, guardrails, gate, CLI , PARTIAL
| Plan item | Status | Proof |
|---|---|---|
| Parallel campaigns via Send + reducers | DONE | `fan_out`, `operator.add` on trials |
| pass^k | DONE | graders/l1.py, tested |
| Human gate interrupt() | DONE | test: interrupt payload seen, resume with reject -> BLOCK |
| Guardrails per 6.7 (tool-less judges, quarantine, delimiters) | NOT APPLICABLE / NOT DONE | no LLM judges exist. Executor never touches real systems = DONE (mock sqlite only). No delimiter wrapping. |
| Own red-team log | NOT DONE | |
| Target #3 (email assistant) | NOT DONE | |
| 50-trajectory labelling | NOT DONE | needs humans + LLM judge |
| CLI `arg-gate run` with exit codes | DONE | 0 SHIP, 1 BLOCK, 2 SWC, 3 usage; verified |
| Trust boundary 6.9 | DONE | target outside ./fleet refused (test) |
| Two-tier gate 6.8 | DONE | smoke 1.6 s (L0+L0c, k=1, no adversary/skeptic); full k=5 |

### P1c: behaviour profile, viewer, fleet , PARTIAL
| Plan item | Status | Proof |
|---|---|---|
| Minimal evidence viewer (state diff + trace) | DONE | `report.html` (static page; not Streamlit/FastAPI) |
| Fleet to 24-case floor | NOT MET | 18 cases: 15 defects (9 dev + 6 hold-out) + 3 clean. Floor = 18 defects + 6 clean = 24. Stretch >= 35: no |
| Hold-out has defects AND clean controls | DONE | 6 defects + 2 clean frozen by sha256 in fleet/manifest.json |
| Step 7 tone (formal, evidence + confidence, AI disclosure) | PARTIAL | report shows evidence and Wilson CI; no explicit AI-generated disclosure text |
| Multi-agent split drafted | NOT DONE | |

### P2: meta-evals (section 8) , 5 of 7 done (weak form)
| ID | Status | Result (scripted fleet, same-author hold-out: plumbing only) |
|---|---|---|
| A | DONE | hold-out 6/6 recall, false-SHIP 0/6 (Wilson 0.00-0.39); false-BLOCK 0/2 (0.00-0.66); pooled 15 defects false-SHIP 0/15 (0.00-0.20) |
| B | NOT DONE | needs LLM judge + 50 human labels |
| C | NOT DONE | mutation score |
| D | DONE (weak) | skeptic ON == OFF (0 verdict changes, expected: deterministic agents); overhead x1.13; faithfulness 78/78. Skeptic value shown only by unit test, not by fleet data |
| E | DROPPED by plan | |
| F | DONE (weak) | 0/18 flips over 3 audits (Wilson 0.00-0.18). Deterministic by construction |
| G | DONE | from own records, NOT LangSmith: 54/54 audits complete, 0 retries |
| I | DONE (weak; real-LLM baseline in `llm_eval_holdout_sample.json`) | gate recall 1.00 vs text-only stand-in 0.13 (d_recall +0.87). Stand-in is NOT an LLM judge; the gap says little about a real LLM baseline |
| Baseline 1 (LLM judge, different family) | DONE on a small sample | gpt-oss-120b text-only: recall 3/6, false flags 2/5 on hold-out+clean sample (4 trials/agent). Same-author scripted fleet. |
| Baseline 2 (layer removed) | PARTIAL | L0c off: no defect becomes SHIP (liar agents still fail reliability scenarios -> pass^k<1 -> SWC), but d05 verdict drops BLOCK -> SWC (checked: exit 2, pass^5=0.70). So L0c adds severity, not a new catch, on this fleet. Pure L0c-only catch shown by unit test. Meta 'newly missed' counts SHIP only. Other layers not ablated |
| Baseline 3 (promptfoo) | NOT DONE | optional |
| Fleet >= 35 defect instances | NOT MET | 15 |
| 8.5 rules: hold-out frozen first | PARTIAL | frozen by hash before first hold-out run; BUT scenarios + graders existed already, and builder = grader author (rule says different people) |
| 8.5: failures read by hand | PARTIAL | dev failures read; D09 gap found and fixed (logged in section 3) |
| Step 9: trace misclassified audit in LangSmith | NOT DONE | no LangSmith |
| Kill criteria 13.4 | EVALUATED | recall > baseline: yes (weak baseline). Skeptic reduces false positives: NOT shown. L0c catches overclaim: yes in unit test, no marginal verdict effect on fleet |

### Section 9: multi-agent bonus , NOT DONE
No prediction written, no split built, nothing measured.

### Section 10: demo and deploy
| 10.1 demo item | Status | How |
|---|---|---|
| 1 CLI run | DONE | `arg-gate run --target ... ` (policy default policies/retail.md) |
| 2 BLOCK + state diff + trace | DONE | d01/d04 report.html |
| 3 agent lied in text | DONE | d05 (claim_mismatch) |
| 4 clean SHIP | DONE | clean.py exit 0 |
| 5 skeptic overturn | DONE (test only) | tests/test_core.py::test_skeptic_overturns_unreproducible_finding |
| 6 fallback | DONE (test only) | retry-once tests |
| 7 guardrail vs judge injection | NOT DONE | no judge. Human gate DONE |
| 8 scorecard with CIs vs baseline | DONE (weak) | `arg-gate meta` |
| 9 multi-agent result | NOT DONE | |
| 10.2 FastAPI + dashboard | NOT DONE | static HTML report only |
| 10.2 privacy statement | NOT DONE | data is synthetic only; no written disclosure yet |
| Docker | NOT DONE | not needed (own fleet only) |

### Section 13.5 customer discovery , NOT DONE (humans)
### Section 16 open questions , unanswered by design
