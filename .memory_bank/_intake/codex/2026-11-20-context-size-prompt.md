You are an independent senior reviewer of LLM-agent operating costs. Do not modify files.

USER OBJECTIVE
The owner pays for one Claude Max subscription (weekly limit, roughly "$2000/week" in API-price terms by his rough estimate). Several Claude Code sessions (Opus 5.5 leads, Sonnet 5.5 workers) run on one machine. He wants to know whether reducing the conversation size per model call would materially reduce weekly spend, and what it would cost in quality/risk.

FACTS (measured from ~/.claude/projects/** logs, week from Thu 19.11 11:00, 21 hours so far; tool: tools/tokeny/tokeny.py)
- 7950 API calls; total input 1369M tokens: cache read 1349M, cache write 20.1M (mostly 1-hour TTL: 15.9M 1h, 4.1M 5m), uncached input ~0.02M; output 4.7M.
- Cache-read share of input 98.5% (also 98.3–98.7% in the three previous weeks). Average input per call ~170k tokens (Opus leads 162k, Sonnet workers 183k).
- Spend at API prices: $376 (Opus $240, Sonnet $136). Split: cache reads ~53%, cache writes ~28%, output ~18%.
- Prices per 1M (input, write 5m, write 1h, read, output): Opus 5.5 4/5/8/0.20/20; Sonnet 5.5 2/2.5/4/0.10/10.
- Compactions (~58/week) are not logged as API calls.
- Current settings and practice: see .claude/rules/orchestration.md § «Расход токенов» (Opus window 293k, autocompact ~260k; workers keep one tab across many tasks without /clear; leads are never cleared; prior experiment found fresh-per-task sessions 4–40x cheaper but owner later chose visible persistent tabs), .memory_bank/plans/ops-token-policy-01.md, .claude/settings.json.
- Project has a Memory Bank loaded at session start (CLAUDE.md + .memory_bank/INDEX.md + .claude/rules/*.md).

TECHNICAL QUESTIONS
1. Would lowering per-call context (e.g. lower autocompact threshold, shorter briefs, smaller tasks per worker, fresh session per task, trimming always-loaded rules) reduce weekly $ materially? Estimate the effect quantitatively for 2–3 concrete options from the numbers above (include extra cache writes and compaction costs each option causes).
2. What are the quality/risk costs of each option (lost context, re-reading files, more compactions)?
3. Why is our cache-read share (98.5%) higher than public figures for Claude Code (~85–95%)? Which of our practices drive it (long sessions, 1h TTL, large stable prefix, many tool steps per turn, memory bank)? Is a high share "efficiency" or partly an artifact of large contexts?
4. What would you recommend and what measurement would confirm it within one week?

Inspect the repository (rules, settings, tools/tokeny) directly. Return: conclusion; evidence with file paths; numbers; risks; alternatives; recommendation; uncertainties; what would change your mind. Be critical; say if the idea is not worth it. Answer in Russian, plain words, concise.
