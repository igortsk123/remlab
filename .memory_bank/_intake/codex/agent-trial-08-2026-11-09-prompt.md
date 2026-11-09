Critique this plan before it goes to the owner. Repo: remlab (read-only). Answer in English or Russian, under 60 lines. Be concrete, cite file:line.

Plan: `.memory_bank/plans/agent-trial-08-demo-as-template.md`. Parent: `.memory_bank/plans/MASTER-agent-trial.md`.
Owner decision (fixed, do not argue): after upload the waiting page with ticks stays, then the page must become exactly our existing `/demo` built for the uploaded plan. `/demo` is the template; do not build a separate viewer. Missing things such as floors are added to `/demo`. Empty rooms with a spinner first, then furniture appears with an animation. Everything is automatic.

My own view: serve the same `tools/scout/flat215-demo/index.html` at `/try/<id>/tour/` with per-job `demo-data.json` (the page fetches it by relative path, index.html:1471), switch trial behaviour by a `D.trial` field in the data, never by a fork of the page. I expect the main risks to be (a) live `/demo` regressions because the file is published nightly from main, (b) photo/camera registry key collisions between jobs, (c) `load()` needing a variant, so an empty variant `items: []` is needed, (d) plan drawing `flatPlan()` is a hand abstraction of one flat.

Check against the code and tell me:
1. Is same-file-plus-per-job-data the right mechanism? What in `index.html` or its absolute `/demo/lib/...` paths breaks when served from `/try/<id>/tour/`? Should the HTML come from `/srv/demo` at request time, or be copied per job?
2. Does `D.trial` in data suffice to keep live `/demo` unchanged, or are there code paths that run before data loads?
3. Is an empty variant `items: []` safe through `load()`, `viewShot`, `fitBadge`, cameras, and the home screen? What else assumes at least one item?
4. Floors: is `storey` on rooms with unique room ids the smallest correct change given `demo-rooms.ts` special-cases `living` and `floor` already means the building storey?
5. What order of work gets the owner a visible end-to-end result soonest, and what in the plan should be cut?
6. Anything missing: security of serving per-job data, the paid "make realistic" path, retention, cache headers in Caddy for `/try/*`.
