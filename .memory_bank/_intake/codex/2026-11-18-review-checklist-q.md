You are an independent senior engineering reviewer. Do not modify, create or delete files.

CONTEXT
Project remlab: a lead agent (Claude Opus) accepts work from worker agents (Claude Sonnet) — code changes (Python pipeline
tools/scout/**, Next.js app, static demo page tools/scout/flat215-demo/index.html), data runs, memory-bank edits, UI design.
The owner wants ONE universal review procedure the lead always follows, so nothing is forgotten.
Read: .claude/rules/orchestration.md (sections «Цикл задачи», «Формат отчёта», «Конвейер, не заплатка», «Границы»),
.claude/rules/agent-workflow.md, .claude/agents/verify.md, .memory_bank/lessons/devops-deploy.md (recent lessons 700+),
.memory_bank/core/lessons.md, tools/ops/prepush_check.py, tools/ops/conveyor_check.py, .github/workflows/ci.yml.

DRAFT under review: .memory_bank/_intake/codex/2026-11-18-review-checklist-draft.md

QUESTION
1. Critique the draft: what important review checks are missing (look at past failures in lessons — e.g. CI red for hours,
   hollow verification, scope blow-up, uncommitted edits in the main copy going live via cron)? What is redundant or too long
   to be followed in practice?
2. Which items can be automated by an existing or small new script (e.g. a review helper that prints diff stats, touched
   consumers, IDs-in-code, RU/EN pairs, DEMO_INPUTS, tmp hygiene, typecheck need) so the lead runs one command instead of
   remembering? Point to existing tools that already do parts of it.
3. Propose the final structure: a short always-on rule (≤15 lines) + a detailed guide; and a verdict template.

Return: conclusion; missing/redundant items with evidence (file paths, lesson numbers); automation proposals with exact
existing tools; final proposed checklist text (Russian is fine); uncertainties.
