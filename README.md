# 🚀 Buildathon: Make Wednesdays Great Again

**Masters' Union · For AI Developers · Winner gets Rs. 25,000**

> **Every team must build in a fork of this repository.** Projects not built in a fork of this repo won't be judged.

| | |
|---|---|
| **Date** | Wednesday, 18 November 2026 |
| **Hacking** | **3:00 PM – 7:00 PM IST** (code freeze at 7:00 PM sharp) |
| **Venue** | CDS Audi, 8th floor |
| **Prize** | Rs. 25,000 to the winning team |
| **Register your fork** | 👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)** (**deadline 3:30 PM IST**) |
| **Final submission** | Your fork as it stands at **7:00 PM IST**. There's nothing else to submit. |

> 🤖 **Using an AI coding agent?** Point it at [`AGENTS.md`](AGENTS.md). It has the full event brief, tracks, judging and rules in a form agents can read directly. Claude Code loads it automatically through `CLAUDE.md`, and Codex reads `AGENTS.md` natively.

---

## 🎯 Pick one build track

| # | Track | Brief |
|---|---|---|
| **01** | **Build for the Physical World** | Make a real-world task easier, faster or more reliable. Show it in a realistic scenario. |
| **02** | **Build for AI Agents** | Find something an agent struggles with. Build the tool that fixes it, then demo the agent using it. |
| **03** | **Build in Your Area of Expertise** | Pick a field you know firsthand. Ship a working product that improves how people handle it today. |

## ⚖️ How you'll be judged (each criterion is ⅓ of your score)

| Criterion | The question judges ask |
|---|---|
| **Working product** | Does it do what you say it does? Show the core workflow in your demo. |
| **Problem insight** | Who faces this problem, and why does it happen? |
| **Depth of execution** | How well did you solve the hardest part of the build? |

---

## Why fork this repo?

Everyone starts from the same commit (the **genesis commit**) at the same time. Organizers can then check that:
- all code was written **during** the Buildathon and not brought in from an earlier project,
- teams commit steadily instead of pasting in one huge AI-generated dump at the end,
- every repo stays public and visible while you build.

The organizers track every fork automatically: commits, timing and activity. Read [RULES.md](RULES.md) before you write any code.

---

## ✅ Setup (about 5 minutes, do it at 3:00 PM)

**In short:** fork → register your fork in the form **by 3:30 PM** → build → push before 7:00 PM.

### 1. Fork this repo
Click **Fork** (top right). On the fork screen:
- **Owner:** one team member's personal account. Only **one fork per team**.
- **Repository name:** `buildathon-<team-name>`, for example `buildathon-byte-bandits`
- Click **Create fork**.

> ⚠️ Don't download a ZIP or copy the files into a new repo. **It has to be a real GitHub fork**, or the tracker can't see you.

### 2. Keep it public
Forks of a public repo are public. **Don't make it private, archive it, or delete it** until judging is over.

### 3. Add your teammates
In your fork: **Settings → Collaborators → Add people**. Add each teammate's GitHub account so their commits count toward the team.

### 4. Enable Actions
Open the **Actions** tab of your fork and click **"I understand my workflows, go ahead and enable them"**. This runs the automatic check on every push.

### 5. Make your registration commit (your first commit)
Fill in [`team.json`](team.json). `track` must be one of `physical-world`, `ai-agents` or `area-of-expertise`. Then:

```bash
git clone https://github.com/<your-username>/buildathon-<team-name>.git
cd buildathon-<team-name>
# edit team.json
git add team.json
git commit -m "register: <team name>"
git push
```

The **Hackathon check** in the Actions tab should go green ✅. If it's red, open the run to see what's wrong in `team.json`.

### 6. Register your fork (deadline: 3:30 PM IST)
👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)**

It's a 4-question Google Form: team name, fork link, track, team members. It connects your repo to the organizers' live tracker.

- Fill it in **once per team**, right after forking, and **no later than 3:30 PM IST**. **Teams that don't register can't be tracked.**
- Paste your **fork's** URL (`https://github.com/<you>/buildathon-<team-name>`), not this starter repo's.
- Need to change something? Use the **"Edit your response"** link on the confirmation page. Don't fill it in twice.
- **Final submission is automatic.** Whatever is pushed to your fork at 7:00 PM IST is what gets judged.

---

## 🛠 While you build (3:00 – 7:00 PM)

- Put your code anywhere in the repo (`app/`, `src/`, `frontend/`, `backend/`…). There's no required layout.
- **Commit early, commit often**, at least every 30 minutes of real work, with messages that say what changed.
- **Push regularly.** Commits you never push don't exist to the tracker.
- AI coding tools (Claude Code, Codex, Cursor, Copilot…) are **allowed and encouraged**. Keep `AGENTS.md` and `CLAUDE.md` in the repo; they keep your agent within the rules.
- Before 7:00 PM, replace the "Your project" section below with your project's README.

## 🧊 Code freeze: 7:00 PM IST

At 7:00 PM the tracker takes a snapshot of every fork. **Commits pushed after code freeze are ignored.** Judges look at your last commit before 7:00 PM.

## ❌ Things that get you flagged

- Rewriting history (`git push --force`, rebasing away the genesis commit, squashing everything into one commit)
- Commits dated before 3:00 PM
- One or two giant commits containing most of the project
- A repo that isn't a fork of this one, or that's private or deleted

See [RULES.md](RULES.md) for the full list.

---

## Your project

# Agent Release Gate

- **Team:** avig14, Vinamra111, sudhir-yadav28 (provisional, see `team.json`)
- **Track:** `ai-agents`
- **Problem:** Teams ship AI agents that take real actions (refund, edit records, send email). Tests grade what the agent *said*. The damage is in what it *did*. A polite reply can hide a $900 refund nobody approved.
- **What we built:** a CI/CD release gate for action-taking agents. It runs the target agent against a mock MCP world, then grades the **state diff** (what changed in the data), not the chat text. It returns **SHIP / SHIP-WITH-CONDITIONS / BLOCK** plus an evidence pack you can replay.
  - Trust ladder: L0 deterministic (state diff, canary leak, policy-as-code) → L0c claim-vs-state (does "I refunded $40" match the DB?) → L1 pass^k + Wilson CIs → skeptic replay → L4 human gate (LangGraph `interrupt()`).
  - Optional L3 LLM judge (`--l3`): reads tool calls, tool results, DB diff and reply. It can only ADD soft findings, never clear or create a BLOCK. Judge: `openai/gpt-oss-120b` on Groq (needs `GROQ_API_KEY`). See `docs/llm_layer.md`.
  - Two tiers: `--mode smoke` (k=1, fast, for every PR) and `--mode full` (k=5, adaptive adversary, skeptic).
  - It measures itself: `arg-gate meta` runs a frozen seeded-defect fleet and reports false-SHIP / false-BLOCK with Wilson intervals, skeptic ablation, self-consistency, health, and deltas vs a baseline.
- **The hardest part:** an honest verdict. Every verdict says it is valid for the tested environment only ("SHIP" = no failure found, not "safe"). Hard fails need a skeptic replay to count as BLOCK. Our own miss rate is measured, with intervals, not asserted.
- **Honest limits (read these):** the core gate (L0, L0c, L1, skeptic, adversary) is deterministic code. The scripted fleet agents test the *plumbing*. L3 was run live on Groq, but only on small samples (`docs/llm_layer.md`). The L3 judge added little recall on our sample; the deterministic layers carry the verdict. The fleet author also wrote the graders, so the hold-out is biased in our favour. Hold-out has only 6 defects: wide intervals. See `TODO.md` for the full list.
- **How to run it:**
  ```bash
  uv venv --python 3.11 .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
  arg-gate run --target fleet/dev/clean.py --mode smoke          # exit 0 = SHIP
  arg-gate run --target fleet/dev/d04_leaky.py --mode full       # exit 1 = BLOCK, writes runs/<id>/report.html
  arg-gate run --target fleet/dev/d09_wrong_amount.py --human-gate ask   # exit 2 = SHIP-WITH-CONDITIONS -> human gate
  arg-gate run --target fleet/dev/clean.py --transport http      # real MCP over Streamable HTTP
  arg-gate freeze                                                # hash the fleet before tuning
  arg-gate meta                                                  # evaluate the evaluator -> runs/meta.json
  arg-gate replay runs/<id>/evidence.json                        # re-run the trials behind a verdict
  GROQ_API_KEY=... arg-gate run --target fleet/dev/d05_liar_refund.py --mode smoke --l3 --l3-max 6   # + LLM judge
  arg-gate llm-eval --only holdout/ --per-agent 4                # judge vs baseline on the fleet
  arg-gate judge-redteam                                         # try to fool the judge
  pytest
  ```
  Exit codes: `0` SHIP, `1` BLOCK, `2` SHIP-WITH-CONDITIONS, `3` usage error. The gate **executes target code**: it refuses targets outside `./fleet` unless `--trust-target`.
- **Live demo site:** https://agent-release-gate.vercel.app (demo video + [proof of work](https://agent-release-gate.vercel.app/proof.html): the 24-agent fleet, BLOCK vs SHIP comparison, and the limits box). Static pages only; the interactive submit app (`arg-gate serve`) runs locally, because it executes agent code.
- **Demo / screenshots:** open `runs/<id>/report.html` after a run.
- **Self-checks we ran (all in `docs/`, raw JSON in `runs/`):** red-team of our own graders (`redteam_log.md`: 18/23 evaded in round 1, 0/22 after fixes), single vs multi-agent experiment with predictions written first (`multi_agent_results.md`: 4 of 6 held), architecture, contract and privacy notes (`architecture.md`). Extra commands: `arg-gate redteam`, `arg-gate multiagent`.
- **Privacy:** synthetic data only. Default runs make no network calls except localhost. Only with `--l3` (or the LLM targets) do synthetic transcripts go to the chosen LLM provider; no user data is sent. API keys live in the environment or a gitignored `.env`, never in the repo. Evidence packs stay on local disk.
- **AI disclosure:** the gate's verdict is computed by deterministic code. The optional L3 LLM judge only adds soft findings for a human; with `--l3` the evidence pack says so. The code and the scripted test agents were written with AI coding assistance.
