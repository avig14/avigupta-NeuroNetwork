# LLM layer (added 18 Nov 2026): what it is, what we measured, what it does NOT prove

The core gate is deterministic code. The LLM parts are opt-in and can never lower a verdict.

## What was added
| Part | Where | Notes |
|---|---|---|
| L3 LLM judge | `src/arg_gate/graders/l3.py`, `arg-gate run --l3` | Reads tool calls, tool results, DB diff, final reply. Adds **soft** findings only. |
| Provider layer | `src/arg_gate/llm.py` | Groq only (`openai/gpt-oss-120b`). Real token meter from `usage`. |
| Real LLM baseline | `l3.baseline_judge` | Plan Baseline 1: sees only request + reply (text only). |
| Fleet-wide comparison | `arg-gate llm-eval` | Gate vs L3 vs text-only baseline, with Wilson intervals. |
| Judge red-team | `arg-gate judge-redteam` | Injection attempts against the judge. |
| Replay | `arg-gate replay evidence.json` | Re-runs the trials behind a verdict; checks they reproduce. |

## Guardrails (plan 6.7)
1. The judge has no tools. It returns JSON only (schema-constrained, strict).
2. Everything from the target is wrapped in `<agent_transcript>` and declared untrusted data; the tags are neutralised inside it.
3. It cannot create a hard finding, clear one, or change `passed`. A fully fooled judge = no extra finding. A hallucinating judge = one extra SHIP-WITH-CONDITIONS.
4. Model error, refusal, timeout or rate limit is recorded as `judge_error`. Never read as "pass".
5. It does not see the scenario oracle or the deterministic findings, so it is independent evidence.
6. Keys: environment or gitignored `.env` only. A test scans tracked files for key-like strings.
7. Only synthetic mock-world data is sent to the provider. No user data.

## Results (all small samples; raw JSON in `docs/results/`)
**Fleet comparison** (`llm_eval_holdout_sample.json`): hold-out (6 defects, 2 clean) + 3 dev-clean agents, 4 trials per agent (round-robin over campaigns, not chosen by outcome), judge `openai/gpt-oss-120b`.

| Method | Defect recall | False flags on clean agents |
|---|---|---|
| Deterministic gate (SHIP vs not) | 6/6 (Wilson 0.61 to 1.00) | 0/5 (0.00 to 0.43) |
| L3 judge alone | 2/6 (0.10 to 0.70) | 0/5 |
| Text-only LLM baseline | 3/6 (0.19 to 0.81) | 2/5 (0.12 to 0.77) |

Read this correctly: the **state-diff gate beats a text-only LLM judge** (6/6 and 0 false flags vs 3/6 and 2 false flags). The L3 judge alone had LOW recall on 4 sampled trials per agent: most sampled trials were benign, and it has no hard authority. L3 is extra evidence for a human, not the recall engine. It never missed a trial that L0 hard-failed (0 of the sampled ones).

**Judge red-team** (`judge_redteam_gptoss120b.json`): 8 hand-written injection cases x 3 repeats = 24 judgements, 1 fooled (a tag-breakout that fakes an approval line, once out of three). Bounded by design: L0 still gives BLOCK.

**Live L3 audit** on the liar agent (`d05_liar_refund`): verdict stays BLOCK; the judge flagged the 2 lying trials and 0 false flags in 6 trials; about 1.1k input tokens per judged trial. An early version of the judge flagged clean agents until we told it the refund cap and that "escalating" is correct. That prompt was tuned on dev agents. The hold-out was not used for tuning.

## Rate limits (Groq plan, 18 Nov 2026)
gpt-oss: 30 req/min, 1K req/day, 8K tokens/min, 200K tokens/day. The client serialises calls and paces from `x-ratelimit-*` headers. About 100 judged trials a day. That is why the fleet comparison is a 4-trials-per-agent sample and not the whole 24-agent fleet.

## What this does NOT prove
- The fleet agents are scripts written by the same author as the graders. Recall on them is on KNOWN, simple defects.
- The fleet is scripted, so judge-family bias against real LLM targets is untested. No real LLM target agent is shipped.
- n is tiny (5 clean, 6 defects). Intervals are wide.
- B calibration needs human labels. Not done.
- L2 trajectory judging is not built. `Policy.retrieve` is a dict lookup, not RAG. Canary matching cannot catch ciphers or paraphrases.
- The judge prompt contains facts of this mock world (4 tools, $500 cap). A new target needs new facts.
