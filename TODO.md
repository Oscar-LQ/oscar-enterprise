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

9. [Redline] **Decomposition ceiling closed by 10N reframing; 10N capability question SETTLED in the affirmative (Arturs's substantive verdict, three known gaps); 10O planner-executor head-to-head running, substantive verdict pending.** **10O update (this revision):** Sprint 10O ran a planner-executor split against 10N's existing output on the same NDA + brief. Planner = GPT-5.5 non-Pro via OpenRouter ($5/M input + $30/M output; deliberate Arturs choice — GPT-5.5 Pro at $30/$180 is the 10P-target capability-ceiling check); executor = MiniMax-M2.7 (same as 10N). Two-hypothesis test: (a) does the planner-executor split close 10N's three substantive gaps (clause 3 "who have a genuine need to know it" qualifier, clause 7 "Save for liability which cannot be limited or excluded by applicable law" catch-out, cross-clause "mutual obligations throughout"); (b) is GPT-5.5 non-Pro sufficient for the planner role. Phase 0 confirmed Deep Agents 0.5.3 supports per-sub-agent model assignment but not sequential-mandatory primitive — direct Python pipeline chosen, no Deep Agents. Phase 3 single run: planner emitted 4 instructions + 4 cross_clause_notes, parse_method=direct; 4 executor calls all parsed at layer 1; 4 edits applied / 0 skipped via pipeline.apply_edits; nda-output.docx 39,363 bytes, valid zip, w:ins=6, w:del=5. **Outcome A (mechanical) / substantive verdict pending Arturs's review of three specific gap closures.** Planner-layer evidence: gap 1 (clause 3 qualifier) and gap 2 (clause 7 catch-out) explicitly listed in p1/p3 preserve lists — load-bearing field fired as designed; gap 3 (cross-clause mutuality) was JUDGED already-met by the planner ("draft is already framed as mutual in title, party definitions, Confidential Information definition, Clauses 2/3/6/7"; Purpose definition "commercially asymmetric but does not itself make the confidentiality obligations one-sided"). Outcome map: (i) all three gaps close in .docx → architecture + non-Pro tier confirmed; (ii) gap 3 judgement was correct → same; (iii) gap 3 was a real omission → 10P probes GPT-5.5 Pro; (iv) executor didn't honour preserve lists → 10P diagnoses handoff or instruments executor. pipeline.py docstring updated with Adeu upgrade-brittleness warning naming every private surface the inline path imports — flagged for 10P+ refactor onto process_batch (also resolves Q1 comment-attachment via inline path). Q1 comment-fix applied at run.py edits_for_pipeline boundary. — — — **10N reframing (prior update — capability question SETTLED in the affirmative by Arturs's review):** Sprint 10N replaced the malformed test with a representative one. **Substantive verdict: production-acceptable.** Output landed four targeted edits across four clauses with sentence-level surgical anchoring and structurally sound clause replacement (§9 LCIA block as continuous prose). The eleven-sprint capability question — "can MiniMax produce solicitor-shape redlines on a real brief" — is settled in the affirmative. Three known gaps identified (LLM judgement errors, not pipeline bugs): clause 3 dropped "who have a genuine need to know it" qualifier; clause 7 lost "Save for liability which cannot be limited or excluded by applicable law" catch-out; cross-clause "mutual obligations throughout" missed across recitals + Purpose definition. — — — **10N planning context (this update — supersedes the (a)/(b)/(c)/(d) lever tree below):** Arturs reviewed the actual .docx outputs from 10M and concluded the eleven-sprint test was malformed — §9 (governing law + jurisdiction in one paragraph) is structurally flat with no surgical-edit surface area, so the mechanical span-width metrics inherited from CPM Step D1 were measuring against a quality bar the input could not meet. MiniMax's "wide" output in 10K–10M was the only correct shape available given the input. Sprint 10N replaces the malformed test with a representative one: a real solicitor's brief asking for multi-clause review on the same Acme NDA, MiniMax-only, single-shot, with substantive judgement of the produced .docx by Arturs in Word as the success criterion (mechanical span widths captured but informational only). Two infrastructural changes: Adeu 1.1.0 → 1.3.3 upgrade (verified non-breaking against 10M's pipeline imports); user message structure swapped from playbook-format to solicitor-brief + NDA + data contract note. Phase 1 compared **B1** (10M's Vibe system prompt minus the Output Format JSON schema and edit_type Values sections; persona + structured-reasoning + Edit Precision + WRONG/RIGHT preserved) vs **B2** (the four-sentence solicitor system prompt verbatim from the brief); both produced 4 edits with near-identical clause coverage but sharply different shape — B1 surgically anchored, B2 wholesale clause replacements with admitted scope creep. **Both runs and the Phase 3 run missed the mutual-obligations-throughout instruction** — substantive content gap that surfaces on Arturs's review. Phase 3 ran B1 end-to-end via `pipeline.apply_edits` on Adeu 1.3.3: 4 edits applied / 0 skipped, output `nda-output.docx` 39,318 bytes, mechanical verify_output passes (valid zip, parses, w:ins=6, w:del=5, litigation phrase preserved in w:delText). **Outcome A (mechanical) / substantive verdict pending Arturs's Word review** of the .docx on feature branch `sprint-10N-real-solicitor-brief`. Cross-sprint data: (a) **the data contract note dominated over Vibe's structured-reasoning instruction in B1** — MiniMax dropped the `reasoning` object both times; Vibe's classification-framework value is in the WRONG/RIGHT examples and Edit Precision Rules, not in the structured-reasoning + classification scaffold (when data contract is `{"changes": [...]}`); (b) **the eleven-sprint decomposition-ceiling arc is closed by Arturs's reframing, not by 10N's run** — "MiniMax cannot produce narrow surgical-span redlines on §9" stands as a finding about a structurally-flat input clause, not about MiniMax's general capability against representative input; (c) **inline-path Markdown stripping persists from 10M as a known constraint** — `pipeline.py:_strip_formatting_markers` strips `**`/`_` before the inline word-diff path; Adeu 1.3.x's native markdown handling only fires on the delegation path. Phase 3 LLM did not emit Markdown markers, so the constraint did not manifest visibly; if Arturs's review notes lost formatting, lineage traces to 10M's inline-vs-delegation choice — 10O addresses if material. — — — *Historical context (now superseded by 10N reframing — kept for sprint-arc traceability only):* Eight-sprint arc on the same NDA / same §9 litigation→arbitration transformation: 10F (MiniMax identifies clause-level but bundles span-level under document framing), 10G (plan-first discipline ignored — bundling is capability, not planning absence), 10H (confounded by HOC text-drop; control run with hand-wired 10E spans succeeded), 10I (executioner framing makes bundling WORSE — Sonnet 71-word `w:ins`), 10J (Shape B deterministic pipeline mechanically sound but Stage 1 drafter produces wholesale sentence rewrite), 10K (faithful CPM full-scaffold port — persona + authority + Step D1 + worked examples, all verbatim; Outcome C), 10L (port CPM's document-vs-new diff mechanism and re-process 10K's output without any new LLM call; Outcome C). **10L's per-edit comparison is the headline: 10K (direct-Adeu) = 1 block / w:del=29w / w:ins=56w; 10L (mechanism + process_batch) = 1 block / w:del=29w / w:ins=56w — identical.** The ported mechanism did not narrow. **Diagnosis: `diff_cleanupSemantic` (CPM's default cleanup pass, ported verbatim) collapses the scattered short shared runs between 10K's target and new_text into one DEL + one INS.** Raw `diff_main` without cleanup finds 72 tiny ops (including the shared 10-word substring "arising out of or in connection with this Agreement", verbatim in both strings); `diff_cleanupSemantic` reduces them to 2. CPM's narrow OOXML on Opus therefore depends on Opus producing `new_text` with longer preserved phrasing runs than MiniMax's wholesale rewrites — a behavioural dependency CPM's SKILL.md does not disclose. Also from 10L: Adeu's `trim_common_context` DID fire in 10K's run and returned `(0, 0)` — target starts "T" / new starts "A" (no shared prefix); target ends "Agreement." / new ends "parties." (no shared suffix after word-boundary backtrack). The port was required, not side-steppable by re-invoking Adeu differently. **The "missing post-processor" hypothesis is falsified for this transformation.** 10M lever choices, keyed to 10L's diagnosis: (a) conservative-drafting prompting on MiniMax (restore the 10J-dropped preservation sentence; cheapest probe of the upstream-LLM-drafting-style lever — 10L's diagnosis points here); (b) same 10K prompt on a frontier model via env-var flip (distinguishes tier-capability from prompt-scaffolding); (c) cleanup-pass probe — swap `diff_cleanupSemantic` for `diff_cleanupEfficiency` or no-cleanup-with-filtering (isolates the cleanup contribution; directly tests 10L's diagnosis); (d) accept frontier + mechanism as the production shape. Recommendation from 10L: (a) → (c) → (b) → (d). The narrowness lever has at least three points of intervention (LLM drafting, diff cleanup, OOXML emission granularity), and CPM's SKILL.md documents only a mix of the first (Step D1) and third (per-op DOM surgery) — the second (cleanup-pass choice) was invisible until 10L revealed it. 10L's post-processor (find + diff + block-grouping + anchor-widening) is reusable infrastructure for whichever lever (a)/(b)/(c) identifies as load-bearing. **Sprint 10M (faithful port of Vibe Legal Redliner — prompt + one-call pipeline + word-diff + DOM surgery, verbatim from a working production redliner; two runs, MiniMax and Gemini 2.5 Flash):** Outcome C with a novel diagnostic variant. **MiniMax:** 1 edit applying Vibe's MISALIGNMENT-RIGHT anchor-preservation idiom for the first time in the arc — `new_text` begins with a verbatim prefix of `target_text` (the governing-law sentence), which Vibe's word-diff preserved as EQUAL; `w:del=29w` (jurisdiction-sentence only), `w:ins=54w` split across 2 new paragraphs via `_insert_new_paragraphs`; all 5 LCIA elements present in clean-view §9. **Gemini:** 6 edits (1 MISALIGNMENT + 5 GAP), 1 applied and 5 skipped due to a **novel chained-GAP failure mode** — each GAP's `target_text` references the PRIOR edit's `new_text`, which Vibe's pipeline applies independently against the ORIGINAL document; clean-view §9 missing 4 of 5 LCIA elements. Fresh positive data point: **MiniMax DOES uptake anchor-preservation when shown a concrete sentence-level worked example** (10F–10L's prompts told MiniMax to be surgical without showing what a full-sentence RIGHT example of the pattern looks like; Vibe's prompt does). The narrowness failure on 10M-MiniMax is now localised to the *appended new content* being wholesale, not to the anchoring behaviour. Remaining unprobed levers: **10N-a** frontier-tier on Vibe's prompt (Opus/GPT-5.4 env-var flip — cheapest; tests whether tier + Vibe-prompt together produce narrow `w:ins` on the LCIA-machinery insertion); **10N-b** transformation-specific §9-forum-swap RIGHT example added to Vibe's prompt (extends 10K's (b) with 10M's data that anchor-preservation transfers); **10N-c** flat 7-rule playbook on MiniMax (tests whether Gemini's chained-GAP hazard is playbook-format-linked or Gemini-specific); **10N-d** accept frontier-tier as required for §9-like transformations. Recommendation: (a) first, (c) second, (b) third, (d) landing. **Also from 10M:** playbook bullet-as-element vs bullet-as-rule is under-specified in Vibe's format — MiniMax read one rule with seven elements (1 edit), Gemini read seven distinct rules (7 classifications, 6 edits); Oscar playbooks should settle on flat single-rule-per-behavioural-requirement format to match Vibe's `playbook_rules_found must equal analysis.length` expectation cleanly.
   - Trigger: **reached — Substantive verdict on 10O's `nda-output.docx` pending Arturs's Word review (three specific gap closures: clause 3 qualifier preservation, clause 7 catch-out preservation, cross-clause mutuality judgement). Outcome map: (i) all three close → architecture + non-Pro tier confirmed; (ii) gap 3 correctly judged not-a-gap → same; (iii) gap 3 was a real omission → 10P probes GPT-5.5 Pro at $30/$180; (iv) executor didn't honour preserve lists → 10P diagnoses planner→executor handoff**.
   - Source: Sprint 10E scope boundary; Sprint 10F §10G proposal; Sprint 10G architectural-judgement section; Sprint 10H control-run evidence; Sprint 10I primary outcome D; Sprint 10I Sonnet reference outcome C; Sprint 10J outcome B; Sprint 10K outcome C (CPM full-scaffold port on MiniMax does not transfer); Sprint 10L outcome C (CPM find+diff mechanism applied to 10K's output produces byte-identical wide shape; `diff_cleanupSemantic` is the load-bearing collapse step); Sprint 10M outcome C-variant (Vibe faithful-port on MiniMax surfaces MISALIGNMENT-RIGHT anchor-preservation uptake; Gemini surfaces chained-GAP failure mode; neither produces lawyer-shape on §9); Sprint 10N reframing (eleven-sprint test was malformed — §9 has no surgical-edit surface area; replaced with real solicitor's brief on real NDA; Adeu 1.1.0 → 1.3.3 upgrade; B1 trimmed Vibe chosen over B2 short solicitor; Phase 3 mechanical Outcome A; substantive verdict production-acceptable, three known gaps); **Sprint 10O planner-executor head-to-head against 10N (GPT-5.5 non-Pro plans + MiniMax executes; Phase 3 mechanical Outcome A; substantive verdict pending Arturs's review of three gap closures on `nda-output.docx` on feature branch `sprint-10O-planner-executor`)**.

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

50. [Redline] **Multi-channel rendering — MCP Apps UI + Slack-native rendering of Oscar redlines.** Status: TODO; not yet scoped to a sprint. **Background:** MCP Apps launched 2026-01-26 as the first official MCP extension — tools declare a `_meta.ui.resourceUri` pointing to an HTML/JS bundle; host renders in a sandboxed iframe; bidirectional JSON-RPC over postMessage (spec at modelcontextprotocol.io/extensions/apps/overview). Adeu (the OOXML primitive Oscar depends on) added MCP Apps support in v0.9.0 (March 2026); Adeu's `read_docx` tool now renders extracted document text as an interactive Markdown view inside Claude Desktop alongside the agent's reasoning (github.com/dealfluence/adeu — `MCP_APPS_PROTOCOL.md` documents protocol version 2025-11-21). Slack announced Slackbot MCP Client (beta as of April 2026; GA date not announced): "Slackbot also renders MCP Apps to provide rich, app-specific experiences within the chat. By including an MCP server in their manifest, these apps enable interactive UI and tool integrations directly within Slackbot conversations" (slack.com/blog/news/slack-is-where-agents-work). Slack also expanded Block Kit (cards, alerts, carousel, work objects, code, data tables) to provide native rendering primitives for agent responses without iframe execution. Multi-format embedded-resource pattern documented in production: tools return `ui://` for iframe-capable hosts, `slack://blocks/` for Block Kit, `slack://work-objects/` for Slack Work Objects, plain text fallback (rida.me/blog/mcp-embedded-resources-slack-work-objects-block-kit). **Architectural implications for Oscar:** (1) Oscar's redline pipeline could expose tools that return multi-format embedded resources — same pipeline, multiple rendering surfaces: `ui://oscar/redline-review` for Claude Desktop / Cowork (visual document with tracked changes inline); `slack://blocks/oscar-redline-summary` for Slack (decision count, per-clause summary as Block Kit data table); `slack://work-objects/oscar-counter-proposal` for substantive counter-proposals as Slack Work Objects; `.docx` output remains the legal-review substrate. (2) Multi-channel architecture aligns cleanly with G42's advertisement requirement of "integration compatibility with CRM, marketing automation, analytics, content management." (3) Slackbot MCP Client provides a path for lawyers to review Oscar's output in Slack natively when Slackbot MCP Client GAs, without context-switching to Claude Desktop. **Architectural questions deferred for future sprint scoping:** multi-format vs single-format with channel detection (probably multi-format per Rida's production pattern); Slack-native redline UI shape — Block Kit data table for decision summary, Work Objects for clause-level detail, canvas role TBD; latency profile — redline runs take 2-10 minutes, staged response shape needed for Slack (acknowledge → progress → final), Block Kit has progress patterns worth investigating; whether Oscar exposes its redlining capability as an MCP server primarily (with multi-channel rendering) or continues the current pipeline-orchestrator model (with rendering as a separate concern). **Dependencies:** Slackbot MCP Client GA (timing not announced; beta as of late April 2026); Sprint M2's channel abstraction (ADRs 023, 024) provides the foundation for multi-channel output, separately from MCP Apps rendering; Sprint 10Q's playbook layer is rendering-surface-agnostic — no rework needed when rendering surfaces get added later. **Sources:** modelcontextprotocol.io/extensions/apps/overview; github.com/dealfluence/adeu (`MCP_APPS_PROTOCOL.md`, `README.md`); slack.com/blog/news/slack-is-where-agents-work; slack.com/blog/news/mcp-real-time-search-api-now-available; docs.slack.dev/ai/slack-mcp-server; rida.me/blog/mcp-embedded-resources-slack-work-objects-block-kit; blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps. Not in scope for Sprint 10R or any currently planned sprint.
    - Trigger: Slackbot MCP Client GA announced (forces decision on whether to enter beta or wait); OR an MCP Apps deployment becomes the limiting factor in lawyer adoption (currently `.docx` output is sufficient for the test-fixture work); OR G42 production-readying work begins (multi-channel rendering may be a submission requirement).
    - Source: Side-quest TODO register entry, 2026-04-26; MCP Apps GA announcement (2026-01-26); Adeu v0.9.0 release (March 2026); Slack Slackbot MCP Client beta (April 2026); Sprint M2 ADRs 023 + 024 (channel abstraction).

51. [Infrastructure] **M4 — Slack file upload + download.** User attaches `.docx` to a Slack mention; SlackChannel extracts the file URL from `event["files"]`; the redline tool's input schema (already Optional on path fields) accepts the downloaded path; output `.docx` uploaded back via `files_upload_v2`. M3's hardcoded fixture-path defaults in `src/redline/tools/_paths.py` move from "always on" to "M3-only fallback that disappears entirely". `OSCAR_AGENTMAIL_*` provisioning likely lands in the same window.
    - Trigger: Sprint M3 closed (2026-04-28); next sprint up.
    - Source: M3 plan § 9 Out of scope; M3 SPRINT_LOG carry-forward.

52. [Infrastructure] **Playbook layer — Store-backed playbooks.** Replace the per-client `.docx` design direction (10Q research note + addendum's draft ADR 026) with LangGraph Store-backed playbooks under `("deployment", "playbooks", <document_type>)` namespace. Playbook sprint reads the addendum's draft text at `/sandbox/oscar-m2-addendum/docs/adr/026-playbook-as-per-client-docx.md` for context, decides on Store layout, writes a new ADR superseding the 10Q direction. The 10Q paused branch's Phase 1.3 four-context-layer planner-prompt restructure (`bd1f236`) may be salvageable at the prompt-builder layer when the playbook context exists on `main`.
    - Trigger: when a second playbook rule appears (item 2's threshold) OR M4 closes.
    - Source: M3 plan § 9; 2026-04-28 architectural handover.

53. [Infrastructure] **Practice-area heads sprint — Head of Commercial first.** Replace Oscar's "this work needs a partner-level review" fallback with delegation to a Head of Commercial Deep Agent. ADR 014's `CompiledSubAgent` nesting pattern still applies. HOC's specialists (accept-reject-reasoner, redline-specialist, etc.) become reachable again. Other heads (Employment, M&A, Compliance, Privacy, Litigation, CoSec) slot in alongside HOC without a refactor.
    - Trigger: capability expansion past M3's single-tool front door.
    - Source: M3 plan § 9; supersedes item 47 by naming Head of Commercial as the first concrete head.

54. [Infrastructure] **LangGraph singleton-agent issue (#2040): per-conversation `asyncio.Lock` in dispatcher.** Same-thread concurrent inbounds step on the shared `MemorySaver`. M3's fixture-path single-user test does not hit it. The fix is a per-conversation lock keyed by `conversation_id` in the dispatcher; takes a few minutes to write and a unit test to pin.
    - Trigger: second concurrent user appears OR an in-thread race bites in production.
    - Source: M3 plan § 8 Risk 3; SPRINT_LOG carry-forward (ii).

55. [Infrastructure] **Profile per-invocation agent rebuild memory pressure.** Each inbound message constructs a fresh `CompiledStateGraph`. Cost is millisecond-scale; allocation pressure is unmeasured. A long-running runtime over many conversations may show GC pressure.
    - Trigger: production hours visible OR M4's file-handling adds further per-invocation allocation.
    - Source: M3 plan § 8 Risk 6; SPRINT_LOG carry-forward (iii).

56. [Infrastructure] **Housekeeping sprint — documentation gaps + obsolete env-var triples.** (a) Write the missing ADR 001 (referenced by ADR 002 as "pending"; never authored). (b) Decide on `oscar_config.yaml` (PROJECT.md line 137 lists it as a project-root file but it does not exist; either create it with appropriate content or remove the reference). (c) Delete the `OSCAR_LLM_GENERAL_COUNSEL_*` and `OSCAR_LLM_REDLINE_SPECIALIST_*` triples from `.env.example` (annotated `# UNUSED as of M3` in the same sprint; deletion deferred to avoid mixing structural and cosmetic changes).
    - Trigger: a sprint with low-substance bandwidth OR M4 close.
    - Source: M3 plan § 7 conflicts 8 + 16; SPRINT_LOG carry-forward (iv).

57. [Infrastructure] **`OSCAR_LLM_OSCAR_*` triple on host (operator action).** M3's runtime requires `OSCAR_LLM_OSCAR_PROVIDER`, `OSCAR_LLM_OSCAR_MODEL`, `OSCAR_LLM_OSCAR_API_KEY` in `/etc/oscar/oscar.env`. Without these, the orchestrator's `get_chat_model(env_prefix="OSCAR_LLM_OSCAR")` raises `ValueError` at runtime startup and the live integration test skips. Recommended values: `openrouter` / `openai/gpt-5.5` / the existing OpenRouter API key. Note: ADR 010's per-role allocation principle means the same key already on the host (used by `OSCAR_LLM_GENERAL_COUNSEL_*`) can be reused.
    - Trigger: before M3 sprint close; live integration test cannot run without it.
    - Source: M3 SPRINT_LOG carry-forward (i); plan § 5 Phase 0.
