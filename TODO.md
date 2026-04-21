# TODO.md

Items we've deferred, flagged for later, or identified as worth revisiting. Each item has a trigger — a specific condition or event that should prompt return. Not a backlog; persistent context that spans sprints.

## Architectural decisions

1. [Redline] **Multi-turn `reasoning_details` preservation for MiniMax specialists.** ADR 012 records a three-step plumbing plan (LangChain message-conversion extension, task-tool forwarding, `<think>`-wrapper reconstruction) explicitly deferred; today's fix discards the split field.
   - Trigger: first sprint that wires a multi-turn specialist conversation where chain-of-thought continuity matters.
   - Source: Sprint 8; ADR 012.

2. [Redline] **Supersede ADR 015 — move playbook rules from inline system-prompt text to a registry.** Rule GL-001 lives hardcoded in `accept-reject-reasoner`'s prompt; multi-rule prompts become unwieldy.
   - Trigger: second playbook rule, or first request for a human-editable rule.
   - Source: Sprint 9; ADR 015.

3. [Redline] **Persistent playbook storage layer (Postgres table or YAML-in-repo).** Partner decision to the ADR 015 supersede — turns rules into versioned, human-editable data.
   - Trigger: once ADR 015 is superseded.
   - Source: Sprint 9 next-sprint direction (c).

4. [Infrastructure] **HITL (`interrupt_on`) per-compile-site configuration pattern.** `CompiledSubAgent` does not inherit the parent's `interrupt_on`; every nested Deep Agent must configure HITL at its own compile site.
   - Trigger: first sprint that wires human-in-the-loop interrupts.
   - Source: Sprint 9 surprise 3; ADR 014 (caveat in `graph.py:388-392` docstring).

5. [Infrastructure] **Latent `general-purpose` subagent at every nesting level.** Currently three in the GC→HOC→specialist tree; enforcement is prompt-only. Building an agent without `SubAgentMiddleware` requires hand-constructing the middleware stack (no `subagents=False` switch).
   - Trigger: a routing incident where a GC/HOC/specialist delegates to `general-purpose`, OR a four-level tree compounds the surface.
   - Source: Sprint 6 surprise 3; Sprint 7 surprise 1; Sprint 9 surprise 5.

6. [Infrastructure] **Default Deep Agents filesystem tools contaminate restricted-tool specialists — must-fix for top-level MiniMax use.** `FilesystemMiddleware` unconditionally injects `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` at every agent level (top-level and sub-agent). OPERATING DISCIPLINE's "no filesystem access" line is prompt-level fiction — the tools exist and can be called against a virtual `StateBackend` that does not see Adeu's real-filesystem closure. In 10G this surfaced as a reasoning-layer confusion that MiniMax internally overcame; in **10I primary it was blocking** — top-level MiniMax with a path-referencing HumanMessage went `read_file` → `ls`×3 → `glob` → "file not found" → zero edits. Prior sprints' sub-agent shape concealed the problem because sub-agent HumanMessages are `task`-synthesised without explicit path references. **10I Sonnet reference showed the same framework is tolerated by Sonnet** — the failure is model-specific under path-referencing prompts, not universal. Options: (a) build a `_ToolExclusionMiddleware`-equivalent that strips FilesystemMiddleware's tools (framework-level fix, bounded blast radius); (b) keep MiniMax off top-level roles and restrict it to sub-agent shapes via `task`; (c) drop the path reference from top-level HumanMessages and let the agent discover the file only through the bound Adeu tools.
   - Trigger: **reached — 10I primary's zero-edit outcome. Must-fix before any top-level MiniMax experiment.**
   - Source: Sprint 10G surprise 4, carry-forward (iv); Sprint 10I primary (blocking); Sprint 10I Sonnet reference (shows model-specificity).

7. [Infrastructure] **Acknowledge broker-vs-direct sovereignty distinction in PROJECT.md § LLM Policy.** OpenRouter is a US broker fronting many upstreams — data-residency decisions move from provider-choice to model-slug-choice. Currently in `OpenRouterClient` docstring and `.env.example` only.
   - Trigger: second concrete client configuration that forces a residency decision, OR first client with PRC/EU/UK residency constraint.
   - Source: Sprint 4 surprise 3.

8. [Redline] **HOC output-envelope hardening — must-fix before Shape A goes anywhere.** HOC's paraphrasing hazard has been observed in four distinct shapes across 10D/10F/10G/10H: (a) adding hallucinated narration to specialist output (10D); (b) producing faithful relays sometimes and paraphrasing others (10F/10G, intermittently); (c) dropping critical input text when relaying the user's request to a specialist (10H primary); (d) fabricating a fake filesystem-search narrative as a fallback when a specialist ERRORs (10H primary). Options: tighten "relay verbatim" rule (already tried, ineffective); have specialists return a JSON envelope (`status`, `output_path`, `summary`) that HOC reads literally; replace MiniMax HOC with frontier HOC for routing tasks that carry complex text payloads; or architecturally bypass HOC for specialist-facing text relay (Python orchestrates). 10H Sprint proposal (a) and (b) demonstrate the last two options.
   - Trigger: **reached. must-fix before next Shape-A experiment.**
   - Source: Sprint 10D surprise 3, carry-forward (iii); Sprint 10E carry-forward (i); Sprint 10F (i); Sprint 10G carry-forward (i); Sprint 10H surprises 1 and 2.

9. [Redline] **Decomposition ceiling confirmed across seven consecutive framings — 10K Outcome C closes the CPM-port hypothesis and forces an architectural choice.** Seven-sprint arc on the same NDA / same transformation: 10F (MiniMax identifies clause-level but bundles span-level under document framing), 10G (plan-first discipline ignored — bundling is capability, not planning absence), 10H (confounded by HOC text-drop; control run with hand-wired 10E spans succeeded), 10I (executioner framing makes bundling WORSE — Sonnet 71-word `w:ins`; ceiling is prompt-framing not model-tier), 10J (Shape B deterministic pipeline mechanically sound but Stage 1 drafter produces wholesale sentence rewrite — bundling moved upstream to drafting), 10K (faithful port of CPM's first-pass pattern — LLM edit-list contract + Step D1 surgical discipline + WRONG/RIGHT worked examples + authority framework + persona + commenting rules, all verbatim). **10K Outcome C — CPM's full-scaffold prompt did not unlock surgical spans on MiniMax: one edit, `target_text`=29 words, `new_text`=56 words, `w:ins`=56 OVER-BROAD, `w:del`=29 SUSPICIOUS. Same bundled shape 10G/10I-Sonnet/10J produced under simpler prompts.** 10J's framing ("bundling moved to drafting") was itself downstream of the mis-port — 10J was not actually porting CPM (prose output + document-level diff), while CPM is edit-list output + per-edit diff. 10K corrected the port and the outcome held. **Prompt-discipline transfer is asymmetric: CPM's commenting rule transferred cleanly (zero comments emitted); Step D1 span-size rule did not.** Two non-exclusive readings survive the evidence: (1) CPM's pattern depends on frontier (Opus) decomposition judgement; explicit surgical language is scaffolding that helps but isn't load-bearing on weaker models; (2) the §9 litigation→arbitration transformation is structurally harder than CPM's confidentiality-clause worked examples — edit pairs that cover the substance end up wide because source and target share little prose. Sprint 10L chooses between: (a) add a transformation-specific RIGHT example to the 10K prompt and re-run on MiniMax (distinguishes reading 1 from reading 2); (b) re-run the same 10K prompt on a frontier model (Sonnet 4.6 or GPT-5.4) via env-var flip (distinguishes reading 1 as well — if frontier produces 2–5 narrow edits, pattern is load-bearing on frontier only; if frontier also bundles, pattern needs more than CPM's SKILL.md discloses); (c) accept frontier capability as required for this stage and design the planner/executor architecture around an Opus-tier executor on decomposition, with MiniMax reserved for pre-decomposed apply / review / acceptance stages. Arturs's call which to run next. Further note — Red-Zone pre-authorisation in 10K worked silently (MiniMax produced edit without acknowledging the classification step); whether Step C was consulted at reasoning layer is unknown under one-invocation budget. `reasoning_split=False` local override (10G technique) would surface this cheaply in 10L if needed.
   - Trigger: **reached — Arturs's architectural decision (a) vs (b) vs (c) determines 10L scope**.
   - Source: Sprint 10E scope boundary; Sprint 10F §10G proposal; Sprint 10G architectural-judgement section; Sprint 10H control-run evidence; Sprint 10I primary outcome D; Sprint 10I Sonnet reference outcome C; Sprint 10J outcome B; **Sprint 10K outcome C (faithful CPM port on MiniMax does not transfer; prompt-discipline transfer is asymmetric)**.

10. [Infrastructure] **Subagent tool-call surfacing to the outer message trace.** Deep Agents' `task` tool strips subagent messages; only the final `ToolMessage.content` reaches GC. Current workaround is the `_TOOL_CALL_CAPTURE` + `tool-calls.jsonl` pattern inside tool implementations; it now lives in three sprint directories (10E, 10F, 10G) and the "promote on second call site" bar has been met. Durable fix options: custom middleware that tees intermediate state, or direct second-pass invocation.
    - Trigger: next sprint that uses the pattern — promote to `src/experiments/common/`; OR an audit/compliance requirement for visible specialist reasoning forces a middleware-level fix.
    - Source: Sprint 9 surprise 4; Sprint 10E surprise 1; Sprint 10F; Sprint 10G.

11. [Infrastructure] **`structured_response` propagation through the `task` tool.** Specialist JSON is serialised into `ToolMessage.content` at HOC level but stripped from state before reaching GC. Three options mapped in Sprint 9: (a) second-pass direct invocation, (b) HOC's own `response_format` (forecloses multi-specialist composition), (c) middleware tee.
    - Trigger: a sprint needs specialist JSON available at GC level (e.g., audit log, gate on structured result).
    - Source: Sprint 9 surprise 4; ADRs 013, 016.

12. [Infrastructure] **MiniMax reasoning observability through LangChain.** `reasoning_split=True` (ADR 012 production default) produces `reasoning_content` / `reasoning_details` that LangChain's `_convert_dict_to_message` drops; neither `additional_kwargs` nor `response_metadata` carries them through. Today's 10G workaround is a local `reasoning_split=False` factory override per agent (routes reasoning back inline into `<think>...</think>` content). Production-clean route: custom MiniMax LangChain subclass that overrides dict-to-message conversion to preserve reasoning into `additional_kwargs`. Candidate location: `src/llm/chat_model.py` — a `preserve_reasoning: bool = False` flag on `_minimax_factory`.
    - Trigger: reasoning observability becomes a standing need (second sprint wanting MiniMax reasoning visible beyond a one-off `<think>` inline flip).
    - Source: Sprint 10G surprise 5, carry-forward (iii); ADR 012.

13. [Redline] **Audit-trail protection above Adeu for cross-author rejection.** Adeu's `RejectChange` does NOT gate on author — a counterparty can cleanly reject Oscar's `Chg:N` edits. Qualifies Sprint 10A finding #6. Options: (a) document as known limitation; (b) lightweight facilitator checking author consistency before `RejectChange`; (c) raise upstream with Adeu maintainers.
    - Trigger: the behaviour bites in practice, OR Oscar begins accepting counterparty-signed redlines.
    - Source: Sprint 10C finding 5, Q1.

14. [Redline] **Missing ADR — pin `adeu==1.1.0` and version-bump discipline.** Sprint 10A flagged "ADR to write in 10B" for pin + bump-budget posture; Sprint 10B wrote no ADRs. The 10C test battery (82 tests) is the de-facto regression mechanism.
    - Trigger: Adeu 1.2+ release, OR the first time a bump breaks the battery.
    - Source: Sprint 10A finding 2, risk R7; Sprint 10B "ADRs written: none".

15. [Redline] **Internal-API reach-around policy for Adeu.** Prior art reaches into `adeu.anchor`, `adeu.redline.mapper.DocumentMapper`; Sprint 10A proposed an ADR committing Oscar to the public `__all__` surface "if it becomes a call-site concern." Not yet a call-site concern.
    - Trigger: a sprint needs a behaviour not in `adeu.__all__`.
    - Source: Sprint 10A finding 4 / surprise 4.

16. [Infrastructure] **Deployignore / build-time exclusion of non-runtime files.** PROJECT.md line 131 notes exclusion of PROJECT.md, CLAUDE.md, `docs/adr/` is a build-time concern handled when SIT is stood up.
    - Trigger: SIT stand-up / first packaging pipeline.
    - Source: PROJECT.md § Files in Project Root.

## Prompt and model findings

17. [Redline] **Promote OPERATING DISCIPLINE preamble to a shared template.** Now on three call sites (HOC 10D iteration 2, redline-specialist 10F iteration 2, redline-specialist 10G — inherited from 10F). Same-shape fix each time — forbids file-missing claims, redirects to tool-only operation. 10G refines the finding: the preamble works at the *reply* layer but NOT the *reasoning* layer (visible with `reasoning_split=False`; MiniMax internally hallucinates "file doesn't exist" then overcomes it by re-reading the instruction and proceeding from priors). A prompt-level band-aid, not a full fix.
    - Trigger: third NEW specialist joins Oscar (pattern needs a reusable template), OR reasoning-level confusion becomes a systematic blocker.
    - Source: Sprint 10F carry-forward (iii); Sprint 10D iteration 2; Sprint 10F iteration 2; Sprint 10G carry-forward (v).

18. [Redline] **Defensive fallback for MiniMax structured-output discipline.** Tool-call discipline was ~67% on first-pass prompts in Sprint 9; the preamble lifted it to 100% but remains prompt-level. Candidate: middleware that auto-strips markdown code fences when `structured_response` is missing, OR hard switch to a stronger specialist tier.
    - Trigger: specialist count grows, OR rules become less step-by-step, OR a new intermittent fence-wrapping incident.
    - Source: Sprint 9 surprise 2.

19. [Infrastructure] **Sub-agent response brevity discipline.** Short directional prompts do not produce terse sub-agent output — HOC returned markdown-formatted multi-section replies in Sprint 7. Needs `response_format` constraint or tighter prompt scaffolding.
    - Trigger: a substantive capability sprint that needs clean envelope output from sub-agents.
    - Source: Sprint 7 surprise 2.

20. [Infrastructure] **Planning-tracking is model-discretionary — augment `BASE_AGENT_PROMPT` where needed.** `write_todos` fires only when the system prompt explicitly asks for planning.
    - Trigger: a capability sprint whose work benefits from observable plan tracking.
    - Source: Sprint 6 "Whether and how `write_todos` fired" + next-sprint (a).

21. [Redline] **Add a "nested-on-own-insertion" disqualifier test to the 10C battery.** 10D's duplicate-call produced a structurally-valid but audit-trail-broken redline; 10C's existing `test_edit_inside_existing_insertion` doesn't cover the full-length-match case.
    - Trigger: cheap to do — add on next touch of the battery.
    - Source: Sprint 10D surprise 2, carry-forward (ii).

22. [Redline] **Document asymmetric narrow-del / wide-ins shape in `adeu-idioms.md`.** `trim_common_context` produces this shape when `new_text` includes new machinery the old text didn't have (10F's 12-word del + 33-word ins). Not covered by 10C's symmetric shared-prefix/suffix tests.
    - Trigger: cheap to do — next edit to the idioms doc.
    - Source: Sprint 10F surprise 4.

23. [Redline] **Tool-level rejection of degenerate `target_text == new_text`.** 10F iteration 2's second call was a no-op on identical strings (harmless but diagnostic); 10G iteration 1's observability-failed run showed wasteful-retry shapes of similar flavour, and iteration 2 produced a single clean call with no retries. Not yet at the bar for wrapping.
    - Trigger: third clean-no-op occurrence.
    - Source: Sprint 10F carry-forward (v); Sprint 10G carry-forward (vi).

24. [Redline] **Pick a comment-on-pure-deletion workaround for the redline specialist.** Adeu silently drops comments on deletions. Two ugly options: attach to a retained anchor, or use `new_text=" "` space-padded.
    - Trigger: first transformation that needs a standalone comment accompanying a deletion.
    - Source: Sprint 10C finding 3, Q2; Sprint 10D carry-forward (iv); Sprint 10E carry-forward (iv).

25. [Redline] **Internationalisation: comment-discipline prompt is English / common-law-culture-specific.** Prior-art prompting disciplines imported from Claude-Plugin-MCP assume an English commercial-law drafting register.
    - Trigger: first non-English-law client, OR first civil-law deployment.
    - Source: Sprint 10A risk R8.

## Infrastructure

26. [Infrastructure] **LangSmith tracing — add `LANGSMITH_API_KEY` + policy block for `smith.langchain.com` / `api.smith.langchain.com`.** Silently disabled since Sprint 6.
    - Trigger: first sprint that wants traces for debugging or observability.
    - Source: Sprint 6 surprise 5; Sprint 7/8/9 carry-forwards (ii/ii/vi).

27. [Infrastructure] **`langchain_docs` network policy block — `docs.langchain.com`, `python.langchain.com`, `api.python.langchain.com`.** Currently `docs.langchain.com` returns HTTP 403; sprints work from installed source per "code outranks docs."
    - Trigger: sprint whose brief genuinely depends on hosted docs (not resolvable from source alone).
    - Source: Sprint 2 surprise 1.

28. [Infrastructure] **OpenRouter `HTTP-Referer` / `X-Title` attribution for production.** Current requests are anonymous from OpenRouter's usage-dashboard perspective.
    - Trigger: first client-facing deployment so OpenRouter attributes calls to this workload.
    - Source: Sprint 4 surprise 4.

29. [Redline] **Word UI rendering / Accept-All preview automation.** "Opens in Word" cannot be automated in the sandbox (no Word, no LibreOffice). Mechanical checks + clean-view extraction substitute today; no end-to-end gate for lawyer-shape.
    - Trigger: CI gate or regression harness that needs programmatic Word rendering.
    - Source: Sprint 10A risk R9.

30. [Infrastructure] **Automate per-provider key sanity check at sprint start.** `.env` is git-ignored; Sprint 6 lost ~15 minutes to a stale-key-from-prior-sprint surprise. `docs/secrets.md` documents but does not enforce.
    - Trigger: recurrence of the same surprise.
    - Source: Sprint 6 surprise 1, next-sprint (d).

31. [Infrastructure] **Investigate `sk-cp-...` broker-key prefix if billing or rate-limit behaviour looks unusual.** Not MiniMax's native `sk-...` format but authenticates. Worked; moved on.
    - Trigger: anomalous billing, rate-limit, or authentication signal.
    - Source: Sprint 3 surprise 4.

## Dependencies

32. [Infrastructure] **LangMem integration.** Explicitly excluded from Sprint 1's core install.
    - Trigger: first sprint landing long-term learning / cross-session memory capability (PROJECT.md § Learning).
    - Source: Sprint 1 surprise 5.

33. [Infrastructure] **Postgres variants: `langgraph-checkpoint-postgres`, `langgraph-store-postgres`, `langchain-postgres`.** Excluded from Sprint 1; today's checkpointer is in-memory only.
    - Trigger: first sprint needing checkpoint persistence across `invoke()` calls (e.g., HITL resume, long-running sessions).
    - Source: Sprint 1 surprise 5.

34. [Infrastructure] **LangGraph 2.x upgrade — `config_schema` → `context_schema` migration.** Soft-deprecated in 1.1.8 with removal in 2.0.0.
    - Trigger: LangGraph 2.x release or security advisory.
    - Source: Sprint 2 surprise 2.

35. [Redline] **Adeu version-bump discipline.** `adeu==1.1.0` pinned; 0.9.0→1.0.0→1.1.0 was breaking. The 10C battery (82 tests) is the mechanism; run on any bump.
    - Trigger: Adeu 1.2+ release, dependabot signal, or security advisory.
    - Source: Sprint 10A finding 2, risk R7; Sprint 10C Part 2.

36. [Infrastructure] **`fastmcp[apps]` vendor-strip option.** 60 transitive packages pulled for a dormant-in-SDK-mode server stack; no runtime need.
    - Trigger: transitive dep conflict with a future package, OR security-review pushback on dormant install surface.
    - Source: Sprint 10A risk R2; Sprint 10B install diff.

37. [Infrastructure] **`langchain-perplexity` / LangChain PR #35530 watch.** If merged, the core tag-stripper becomes available as a generic `<think>`-handling utility; today Oscar uses `reasoning_split=True` (MiniMax-specific).
    - Trigger: second reasoning-trace provider joins the seam, OR the PR merges into an installed module.
    - Source: Sprint 8 surprise 4.

## Handoff items

38. [Redline] **Arturs: sign off `docs/reference/adeu-lawyer-shape-criteria.md` (DRAFT).** Still unsigned; 10E/10F/10G self-verified against the respective sprint briefs directly.
    - Trigger: first sprint that needs a shared criteria reference across transformations (T1 "make mutual", T2 "add LoL").
    - Source: Sprint 10C Part 4; Sprint 10D (v); Sprint 10E (ii); Sprint 10F (ii); Sprint 10G (ii).

39. [Redline] **Arturs: Word-level review of `src/experiments/sprint-10e/nda-output.docx`.** Mechanical checks pass; lawyer-shape review is the next gate.
    - Trigger: now — 10E marked output ready.
    - Source: Sprint 10E assessment.

40. [Redline] **Arturs: decide Sprint 10F and Sprint 10G feature-branch merges.** Feature branches `sprint-10f-identification-test` and `sprint-10g-planning-prompt` contain partial results (10F: one wide substantive call + one no-op; 10G: one wide substantive call, reasoning visibly committing to a one-edit bundle). Merge decisions depend on whether the wider shape is acceptable for production given content correctness — if Arturs accepts 10F's shape, 10F/10G are both "successful at the shape level that matters" and 10H shifts from a capability question to a margin question.
    - Trigger: after 10H diagnostic, or on independent human review.
    - Source: Sprint 10F feature-branch commit + next-sprint (c); Sprint 10G feature-branch commit + next-sprint (c).

41. [Redline] **Arturs: four open 10C questions.** (a) non-owning-author reject: document + proceed, or facilitator, or raise upstream? (b) comment-on-deletion workaround: anchor-attach or space-pad? (c) expose `apply_edits_to_markdown` to the agent: yes/no? (d) `adeu.sanitize` exposure: now or defer until counterparty-delivery sprint?
    - Trigger: before 10H, or the first sprint touching any of these surfaces.
    - Source: Sprint 10C §Questions.

42. [Redline] **Superseded by 10I's actual direction.** Original TODO-42 content preserved below for record. 10I took a different direction — single-agent executioner-framing capability test — on the rationale that executioner-capability is logically prior to planner/executor architecture (if the executioners don't work, designing orchestration for them is premature). 10I's joint outcome (MiniMax primary D + Sonnet reference C) collapses the design space onto Shape B (TODO item 9 amendment); the planner/executor Shape A reframe proposed here is no longer load-bearing. HOC text-relay subquestions (original options (a), (b), (c) below) fold into TODO item 8 (HOC output-envelope hardening) where they naturally belong — they are about HOC paraphrasing in general, not specifically about the 10H planner-input hop. The observability housekeeping (expand `_HocInvocationCapture` to all task calls) remains a small standalone item for the first sprint to touch HOC capture.
    - Trigger: **superseded**. Subquestions absorbed into items 8 and 10. Item itself may be deleted on next TODO housekeeping pass.
    - Source: Sprint 10H assessment; superseded by Sprint 10I direction and outcome.

    *Original (2026-04-20, pre-10I):* 10H built Shape A (GPT-5.4 planner + MiniMax executor under HOC) and the primary failed because MiniMax HOC dropped the §9 clause text when relaying to the planner — the planner then emitted a placeholder target_text on first pass and a hallucinated (stylistically-plausible but not byte-matching) target_text on second pass. The GPT-5.4 decomposition-capability question remains untested because the test was confounded. 10I re-runs Shape A with HOC's text-relay unreliability routed around: either (a) inject the NDA's §9 clause text into the planner's system prompt at build time (planner reads clause from its own closure; HOC's task description carries only the transformation instruction), or (b) have the experiment harness orchestrate the planner→executor handoff directly in Python (HOC reduced to "route redline task → Python orchestrator"). Independently, (c) a cheaper diagnostic is to run 10H Shape A unchanged with HOC swapped to GPT-5.4 and see whether frontier HOC preserves the clause text; a short experiment that localises the problem to HOC's text-fidelity as distinct from "MiniMax orchestrators generally". Second-priority housekeeping: expand `_HocInvocationCapture` to record ALL HOC `task` calls.

49. [Redline] **Byte-level fidelity between planner text-in-message and executor on-disk text.** Forward concern flagged in Sprint 10H's plan (Arturs's Addition 2). In synthetic setups (10H primary), the planner's clause text comes from the same `build_input.py` that produces the on-disk `.docx`, so byte fidelity is trivial. For real documents, the planner's `target_text` / `anchor_text` in its plan must match the on-disk OOXML *exactly* (whitespace, non-breaking spaces, smart quotes, tabs). Mismatches cause executor-side Adeu `modify_text` "zero matches" failures. A document-extraction layer converting `.docx` → clause text for the planner must preserve byte-identical text, OR the planner must have a tool that returns canonical on-disk-encoded text.
    - Trigger: first sprint using a non-synthetic (real) NDA input, OR a Shape-A re-run that uses a `.docx` that wasn't generated by `build_input.py`.
    - Source: Sprint 10H plan Forward Concerns section, carry-forward (iii).

43. [Redline] **Run T1 (make-mutual) and T2 (add-LoL) transformations on their own synthetic NDAs.** Proposed in Sprint 10A §3.4 as shape only; never drafted or run. Different decomposition shapes — T1 stresses coordinated consistency (many narrow edits), T2 stresses novel-clause insertion.
    - Trigger: after identification-shape is settled on T3 (10H/10I resolution).
    - Source: Sprint 10A §3.4; Sprint 10E next-sprint (c); Sprint 10F (d); Sprint 10G (d).

44. [Redline] **Real-document + real-playbook ingestion test.** Attach a genuine NDA + playbook and test whether HOC isolates the governing-law clause and routes correctly, or whether a document-parsing layer must land first.
    - Trigger: capability-readiness gate for a first pilot client.
    - Source: Sprint 7 next-sprint (c); Sprint 9 next-sprint (d).

45. [Redline] **Second playbook rule for `accept-reject-reasoner`.** Stress-tests the specialist under multi-rule reasoning; triggers the ADR 015 supersede (item 2).
    - Trigger: capability expansion beyond governing-law.
    - Source: Sprint 9 next-sprint (b).

46. [Redline] **Second functional specialist under HOC.** Candidates: comment-responder, fresh-language drafter, defined-terms auditor. Same `SubAgent`+`response_format` pattern (ADR 013); extends HOC's routing prompt (ADR 016).
    - Trigger: next capability build-out.
    - Source: Sprint 7 next-sprint (b); Sprint 9 next-sprint (a).

47. [Infrastructure] **Second department head under GC.** Company Secretariat, Data Protection, Employment, Property, or Litigation — stresses routing with more than one staffed option.
    - Trigger: capability expansion beyond commercial contracts.
    - Source: Sprint 7 next-sprint (a); PROJECT.md § Capability Stages.

48. [Redline] **Counterparty-response workflow branch.** Oscar today has Claude-Plugin-MCP's "first-pass" branch only; the "counterparty-response" branch (CriticMarkup-detected, multi-round negotiation posture) is not ported.
    - Trigger: capability expansion to multi-round redline exchange.
    - Source: Sprint 10A finding 5.

49. [Redline] **Sanitisation post-step using `adeu.sanitize`.** Relevant when Oscar ships counterparty-deliverable redlines (strip non-delivered comments, clean metadata). `accept_all_revisions()` also purges comments — more destructive than Word UI Accept All.
    - Trigger: first sprint that delivers a redline externally (vs. internal review only).
    - Source: Sprint 10C finding 9, Q4; Sprint 10A.
