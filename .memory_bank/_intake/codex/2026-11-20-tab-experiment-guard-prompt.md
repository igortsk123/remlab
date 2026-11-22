You are an independent senior reviewer. Do not modify files.

CONTEXT
Earlier today you recommended (see .memory_bank/_intake/codex/2026-11-20-context-size-answer.md) a one-week controlled experiment on Sonnet worker sessions: alternate independent tasks between "old persistent tab" and "fresh session", 15–20 accepted tasks per arm, measure median $ per accepted task, calls, fix cycles, time to PASS. The owner approved and said: the director agent tends to forget its own proposals — "make guards so it strictly follows it".

The director (an Opus Claude Code session on pakardev) drafted a plan: .memory_bank/plans/ops-tab-experiment-01.md. Read it, plus .claude/rules/orchestration.md, .claude/settings.json (existing PreToolUse hooks), tools/hooks/ (existing guards), tools/tokeny/tokeny.py and README (how $ per task is attributed via first-line labels "[role] T-…/<cycle> · <phase>"), and ~/.claude/sessions/*.json format if visible.

QUESTIONS
1. Will the guard design actually make the director comply? Where can the experiment silently break (tasks sent via tmux/other machines, labels missing, worker reused, arm chosen by director cherry-picking easy tasks into one arm, fresh session started but brief sent to old tab, sessions renamed, crash of guard)? What is the minimal set of guards that closes the real holes — hard (hook) vs soft (periodic check)?
2. Is a PreToolUse hook on SendMessage feasible and robust here (mapping socket address → session → transcript)? Simpler alternative?
3. Arm assignment: is "alternate / balance by count, stratified by task type" sound for ~30–40 heterogeneous tasks? Would randomisation (e.g. hash of T-ID) be better to avoid the director biasing which task gets which arm? 
4. Measurement: is per-task $ from labels + compaction estimate + fresh-session start cost correct and sufficient? What confounders (task size, paid-machine waiting time, owner-requested rework) must be controlled, and how, with so few tasks? Is the decision rule (−15 % median $, quality not worse than ~10 %) statistically meaningful at n≈15 per arm, or should it be stated differently?
5. Risk: worker count constraint (owner rule "no new tasks on pakardev"). Anything else blocking?

Return: verdict (go / change / drop) on the plan; concrete changes ranked; minimal guard set; what to cut as over-engineering. Russian, plain words, concise. Be critical.
