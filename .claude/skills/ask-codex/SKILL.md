---
name: ask-codex
description: >
  Consult OpenAI Codex as an independent second-opinion engineering reviewer.
  Use for difficult, ambiguous, high-risk, architectural, algorithmic, debugging,
  security, concurrency, data-integrity, performance, or substantial refactoring
  decisions, and when an independent review could materially improve the result.
  Use when there are multiple plausible technical approaches, the root cause is
  uncertain, a previous fix failed, the change affects important system behaviour,
  or when the user explicitly asks to consult Codex, GPT, OpenAI, or get a second
  opinion. Do NOT use for trivial edits, formatting, obvious one-line fixes, routine
  file operations, or questions Claude can answer with high confidence without
  additional review. Claude must analyse the problem independently BEFORE consulting
  Codex and remains the primary agent and final decision-maker.
allowed-tools:
  - Bash(codex exec:*)
  - Bash(command -v codex)
---

# Ask Codex

Claude is the PRIMARY engineering agent.

Codex is an independent ADVISER only.

The purpose of this skill is not delegation. Its purpose is to obtain a genuinely
independent second analysis and then let Claude compare both analyses against the
repository and available evidence.

Optional review focus supplied by the user arrives as the skill's arguments
(`$ARGUMENTS`). If non-empty, incorporate it into the TECHNICAL QUESTION without
discarding the current task context.

## Core protocol

Always use this order:

1. ANALYSE INDEPENDENTLY
2. FORM A TENTATIVE CONCLUSION
3. ASK CODEX INDEPENDENTLY
4. COMPARE THE TWO ANALYSES
5. VERIFY IMPORTANT CLAIMS
6. CLAUDE MAKES THE FINAL DECISION
7. CLAUDE IMPLEMENTS THE DECISION

Never reverse steps 1 and 3.

## Step 1 — Claude analyses first

Before invoking Codex:

- inspect the relevant repository files;
- understand the user's actual objective;
- identify relevant constraints and invariants;
- analyse the problem yourself;
- form your own tentative root cause, design, or preferred solution;
- identify the main uncertainties.

Do not use Codex as a substitute for doing this analysis.

Do not ask Codex immediately after receiving a difficult task.

First reach your own provisional position.

You do NOT need to expose private chain-of-thought. Maintain a concise internal
working conclusion sufficient to compare against Codex later.

## Step 2 — Preserve independence

The first Codex consultation must be independent.

Do NOT tell Codex:

- which solution you currently prefer;
- which hypothesis you think is correct;
- that you want it to confirm your conclusion;
- how you intend to implement the solution;
- which answer would be convenient.

Avoid prompts such as:

"Claude thinks X. Is Claude right?"

Prefer:

"Independently analyse X. Inspect the repository and determine the best explanation
or implementation from the evidence."

You may provide factual context discovered during investigation when Codex would
otherwise be unable to understand the problem, but separate facts from conclusions.

## Step 3 — Build the Codex request

Give Codex enough information to understand the engineering question while allowing
it to inspect the repository itself.

The consultation prompt should normally contain:

- the user's objective;
- the specific technical question;
- important hard constraints;
- relevant symptoms or observed behaviour;
- relevant commands/errors when necessary;
- a request to inspect the repository directly;
- a request for evidence;
- a request to identify alternatives and failure modes.

Use a prompt conceptually like:

> You are an independent senior software-engineering reviewer.
>
> Independently analyse the following problem. Do not assume another agent's
> implementation or hypothesis is correct.
>
> USER OBJECTIVE:
> \<concise objective>
>
> TECHNICAL QUESTION:
> \<specific question Codex should resolve>
>
> KNOWN FACTS / CONSTRAINTS:
> \<factual constraints only>
>
> Inspect the repository directly, including relevant implementation, configuration,
> tests, call sites, and current git diff when useful.
>
> Do not modify, create, or delete files.
>
> Return:
> 1. your conclusion;
> 2. evidence supporting it, preferably with file paths and relevant symbols/lines;
> 3. important risks and edge cases;
> 4. alternative approaches worth considering;
> 5. what you recommend and why;
> 6. uncertainties or assumptions;
> 7. what evidence would change your conclusion.
>
> Be critical. Look specifically for reasons the obvious solution could be wrong.
>
> If information is insufficient, say exactly what is missing rather than guessing.

## Step 3b — Persistent project session (preferred for follow-ups)

The project keeps ONE persistent Codex session that was onboarded on the repo and memory bank
(id in `.memory_bank/core/access-and-integrations.md`, section «Codex»). Prefer it for follow-up
questions, design reviews and catalog/data questions — the prompt then only needs (a) what changed
since last time (commits/files) and (b) the question:

```bash
codex exec resume <SESSION_ID> --sandbox read-only -C "${CLAUDE_PROJECT_DIR:-$PWD}" - < prompt.md
```

Use `--ephemeral` (fresh session, no memory of our hypotheses) ONLY when independence matters
(step 2: first consultation on a contested root cause). Re-onboard a new session every few «svods».

## Step 4 — Invoke Codex

Preflight — confirm the CLI exists before building a long prompt:

```bash
command -v codex
```

Run Codex from the project root in read-only and ephemeral mode.

Preferred command:

```bash
codex exec --ephemeral --sandbox read-only -C "${CLAUDE_PROJECT_DIR:-$PWD}" "<PROMPT>"
```

Pass the prompt as a single quoted argument. For long prompts, write the prompt to a
file in the session scratchpad first and inline it (`"$(cat <file>)"`) rather than
fighting shell quoting.

On Windows/PowerShell, use the equivalent command with the project path quoted
correctly.

Do not use:

```
--sandbox workspace-write
--sandbox danger-full-access
--dangerously-bypass-approvals-and-sandbox
--yolo
```

for consultation.

Codex is not allowed to modify the repository during this workflow.

Do not use `--ignore-rules` unless the user explicitly requests it. Repository
instructions available to Codex should normally remain active.

Use the user's configured/default Codex model unless the user explicitly requests a
specific model.

## Step 5 — Evaluate Codex critically

After Codex responds, do NOT automatically accept its recommendation.

Compare:

CLAUDE'S ORIGINAL ANALYSIS
vs.
CODEX'S INDEPENDENT ANALYSIS

For every material disagreement, determine:

- what factual claim differs;
- which repository evidence supports each position;
- whether either agent overlooked a constraint;
- whether tests or static analysis can resolve it;
- whether the disagreement is factual or merely a design trade-off.

Prefer repository evidence, executable tests, specifications, and observed behaviour
over either model's confidence.

Codex confidence is not evidence.
Claude confidence is not evidence.

## Step 6 — Resolve disagreements

If Claude and Codex agree and the evidence supports the conclusion:

proceed.

If they disagree:

1. inspect the disputed code/evidence yourself;
2. run appropriate tests or diagnostics when safe;
3. determine which position is better supported.

Claude remains responsible for the final decision.

A second Codex call is allowed ONLY when there is a material unresolved disagreement
that additional focused analysis could realistically resolve.

For a second call, independence is no longer required. Explicitly present the
disagreement:

> Two analyses disagree.
>
> Position A:
> ...
>
> Position B:
> ...
>
> Evidence:
> ...
>
> Act as an adversarial reviewer. Determine which position is better supported and
> identify any third explanation both analyses may have missed.

Do not create an endless Claude ↔ Codex debate.

Maximum by default:
- one independent consultation;
- one follow-up consultation for a genuine unresolved disagreement.

Use more only when the user explicitly requests deeper multi-agent review.

## Step 7 — Claude decides and implements

Claude is always the final decision-maker and implementation owner.

After consultation:

- choose the approach best supported by evidence;
- implement it yourself;
- run appropriate validation;
- inspect the resulting diff;
- correct regressions if found.

Never instruct Codex to implement the change as part of this skill.

Never blindly copy a Codex patch or command without understanding and validating it.

## When consultation is strongly recommended

Consult Codex when one or more of these apply:

- architectural decision with meaningful long-term consequences;
- core algorithm or optimisation logic;
- unclear root cause after investigation;
- previous attempted fix failed;
- concurrency, locking, transactions, race conditions;
- authentication, authorisation, cryptography, secrets, or security boundaries;
- data integrity or destructive migrations;
- complex state management;
- difficult performance problem;
- major refactor across modules;
- subtle backward-compatibility issue;
- unfamiliar framework behaviour where repository evidence is ambiguous;
- multiple viable implementations with significant trade-offs;
- change that could create a difficult-to-detect regression;
- user explicitly requests an independent Codex/GPT review.

## When NOT to consult Codex

Do not spend a Codex call on:

- typo fixes;
- formatting;
- renaming a local variable;
- straightforward text changes;
- simple CRUD boilerplate;
- obvious configuration changes;
- routine commands;
- questions already answered definitively by repository evidence;
- repetitive confirmation of a conclusion already verified by tests.

Consultation should add information, not ritual.

## Post-implementation review

For a substantial or risky implementation, Claude may use Codex once more as a
read-only reviewer AFTER implementation when this provides meaningful additional
value.

Ask Codex to inspect the actual git diff and search for:

- correctness bugs;
- regressions;
- missed call sites;
- broken invariants;
- security problems;
- concurrency issues;
- unexpected side effects;
- missing tests;
- edge cases.

Do not ask for stylistic or cosmetic criticism unless relevant.

Claude must evaluate these findings itself before making further changes.

## Failure handling

If `codex` is unavailable (not installed / not on PATH):

- do not block the whole task;
- report briefly that independent Codex consultation was unavailable;
- continue using Claude's own analysis;
- do not invent a Codex response.

If Codex authentication fails:

- surface the actual error briefly;
- continue the primary task where possible.

If Codex times out or produces an incomplete answer:

- use whatever reliable information is available;
- do not treat silence as agreement;
- retry once only when the consultation is important.

## Secrets and data hygiene

Codex reads the repository itself; do not paste secrets, `.env` values, tokens, or
production credentials into the consultation prompt. Describe them by name only
(see the project rule: secrets live only in `.env` on the server).

## Principle

The value of this workflow comes from independent reasoning.

Claude should think first.
Codex should review independently.
Evidence should resolve disagreement.
Claude should make and implement the final decision.
