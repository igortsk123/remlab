You are an independent adviser on how to organise multi-agent work in this repository (remlab). Answer in Russian, concise, concrete.
Do not modify any files.

## Context (facts)
Three machines, each runs Claude Code "lead" sessions talking to the owner through its own Telegram bot; leads give tasks to
"worker" sessions (VS Code tabs / subagents / worktrees). Shared repo: /home/pakar/igor/remlab lives on pakardev and is
sshfs-mounted at the same path on algor and common. Memory bank `.memory_bank/` (git) is the single canonical memory.
Read for current rules: `.claude/rules/orchestration.md` (section «Директор и менеджеры» and «Доска задач»),
`.memory_bank/_intake/peredacha/direktor-2026-11-12.md` (lanes, shared resources, reports),
`.memory_bank/_intake/peredacha/otchety-direktoru.md` (manager reports log), `.memory_bank/plans/README.md` § «Доска задач»
(task board, very long, many stale rows), `.memory_bank/plan-zadach.md` (new owner-facing task plan),
`~/.local/bin/plan-tekst` (renders the plan for the bot command /plan).

## Owner's words today (12.11, voice, verbatim translation-free Russian)
- TG 719–729: «ты директор, они менеджеры, у каждого работники. Каждый менеджер свою часть делает, сам всё перепроверяет,
  тебе отчитывается, а ты мне — по существу. Ты проверяешь только своих работников. Единую сводку и контроль памяти соблюдать.»
- TG 733: «разрешения — через тебя или менеджеров, работники напрямую не спрашивают; я общаюсь через телеграм, не через VS Code».
- TG 744: «Сводку задач храни в одном месте, отдельный раздел "Сводка задач". По приоритетам: П1 с нумерацией задач, краткая
  задача и что она даёт, процент; делаешь сейчас — жирным; П2, П3. Файл в проекте, все к нему имеют доступ — algor, common и ты,
  тогда вы будете распределять задачи и не путаться. Помечай, кто делает (algor, common, ты, работники). В боте кнопка
  "План задач", чтобы я в любой момент видел; не собирать с нуля, а храниться в файле.»
- TG 750/752: формат — строка «П1.1 · algor · 95 %» (жирная только если делается сейчас), с новой строки задача; меньше длинных тире.
- TG 754: «Да, так, окей. Без лишнего текста присылай такую сводку. Сделай распределение задач между всеми так, что если кто-то
  выбывает — токены закончились — любой другой мог подхватить директорство. Работник сделал задачу — отчитывается и сразу
  запрашивает следующую у своего менеджера. Менеджер, если нет задач, обращается к директору; если есть — выдаёт по приоритету.
  Директор управляет приоритетами и также работает сам. Как у людей.»
- TG 756: «обсуди с Codex план и работников, чтобы он помог с организацией именно структуры планирования и организации работы».

## Known pain points
- Owner priorities changed several times; tasks got lost between machines; board rows go stale (dozens of «завершено» rows);
  duplicate sessions; a lead once sent a brief to another project's worker; workers sat 11–13 h on permission prompts no one saw;
  two leads ran memory consolidation in parallel; account token limits stop a session mid-task (weekly limits per account,
  pakardev / algor / common are different accounts).
- Three writers on one file over sshfs.

## Questions
1. Structure of the single source of truth: `plan-zadach.md` (owner view: priority, number, who, %) vs the detailed board
   (T-ID, session journal, state). Keep both, merge, or generate one from the other? Who writes what, how to avoid
   conflicting edits from three machines (sshfs, no locking), and how to keep it from going stale.
2. Pull-based task flow worker → manager → director: concrete protocol (messages, when, what fields), how a manager picks
   the next task by priority, how idle capacity is reported, how the director rebalances lanes without collisions
   (shared files such as `tools/scout/flat215-demo/index.html`, publishing, the Salad GPU pool).
3. Director failover when the director session dies or runs out of tokens: detection (heartbeat? file timestamp?), who takes
   over and in which order, what state must be in files so any lead can continue, how the owner learns who is director now
   (each machine has its own Telegram bot), and how to hand back. Avoid split-brain (two directors).
4. Minimal set of rules to write into `.claude/rules/orchestration.md` — keep it short (the file is loaded into every session).
5. Risks / what typically breaks in such human-like org structures for LLM agents, and what you would NOT do.

Return: recommended design (bullets), exact rule text proposal (≤ 25 lines, Russian), file/field changes, risks, open questions
for the owner (each with your recommendation).
