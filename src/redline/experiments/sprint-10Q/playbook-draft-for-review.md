# Customer-Side Compute Capacity MSA Playbook (Draft)

> **Purpose**: Sprint 10Q's playbook fixture. Prose-style positions
> covering the 13 categories from §5 of the Phase 0 research note.
> Written from training-data knowledge of customer-side enterprise
> AI/cloud contracting practice, *before* reading the OpenAI–CoreWeave
> MSA — testing the abstract → specific capability matters.
>
> **Format note**: this draft is markdown for Arturs's review. On
> approval, convert to `.docx` (`PLAYBOOK-MSA.docx`) for the python-docx
> reader to consume. Conversion is mechanical and preserves the prose
> shape — paragraph breaks, section headings, no bullet structure.
>
> **Audience**: a junior associate or in-house lawyer reading this to
> understand how the senior counsel wants compute-capacity MSAs
> negotiated on the customer side. Style is conversational-but-precise:
> the kind of internal note a partner would write to a colleague, not a
> structured rules-engine output.
>
> **Structure note**: each category states a position and a fallback.
> Whether to walk if the fallback isn't reachable is a tactical
> judgement made deal-by-deal by the partner or in-house lawyer giving
> direction on the specific round. The playbook does not pre-decide
> walk-aways.

---

## Preliminary note

The deals this playbook applies to are large compute-capacity
arrangements — multi-year reservations of GPU clusters or other
specialised AI infrastructure, typically with provider-favourable
default drafting because the providers are oligopolistic and the
contracts originate from their templates. Our instinct on every
clause is to read what the provider has proposed and ask: would a
sophisticated customer with sovereignty concerns, regulatory exposure,
and a multi-year operational dependency accept this without a fight?
Where the answer is no, we push back.

## 1. Data residency and sovereignty

Customer data — inputs, outputs, and provider-generated derivatives —
must remain in jurisdictions the customer names, with cross-border
movement requiring prior approval. We want hard commitments to named
regions for primary production workloads and explicitly contracted
secondary regions for disaster recovery; "best efforts" or
"commercially reasonable efforts" language fails the test, especially
for sovereign-AI customers operating under UAE PDPL, Singapore PDPA, or
similar frameworks that require provable in-country processing.

The fallback we can live with is a hard commitment for primary
production workloads in named regions, with a defined exception
process for short-duration support access by named senior provider
personnel, with logging and customer notification. We do not fall back
on disaster recovery — DR sites are explicitly contracted, not at the
provider's discretion.

## 2. Model and weight ownership

The customer owns all weights and models trained on its data, all
fine-tuning artefacts of base models the customer has licensed, and
all outputs the customer's workloads produce. No provider licence-
back, no improvement-of-service exception, no shared IP interest from
running on provider hardware. Provider IP — base models, provider
software, monitoring tools, the orchestration stack — remains the
provider's, but the line must be drawn explicitly in the contract,
not left to default copyright reasoning.

The fallback is a narrow operational licence to the provider for the
purpose of running the customer's workloads — loading weights into
GPUs, copying between nodes for parallelism, retaining in operational
caches — but only for the term and only for the customer's workloads.
Any retention beyond term, model-improvement use, or non-incident-
response personnel access requires separate written consent.

## 3. SLA tiers

We want tiered SLAs with the highest tier (mission-critical) at
99.95% or 99.99% measured per-availability-zone, with response and
resolution times defined per severity, service credits scaled to
business impact rather than capped at a small percentage of monthly
fees, and a sustained-failure exit right that lets us terminate
without penalty if targets are missed across consecutive measurement
periods. Capacity reservations need both availability and throughput
commitments — TFLOPS sustained, jobs-per-hour at a defined workload
profile, or similar — because a cluster that is "up" but running at
half capacity is not what we are paying for.

The fallback accepts 99.9% on lower tiers and narrower fair-use
throttling rights for genuine abuse cases (AUP violations, workloads
interfering with other customers), provided throttling has objective
triggers, prior notice, and a defined remediation path. We do not
fall back on the sustained-failure exit right.

## 4. Audit rights

Audit rights cover three concerns and SOC 2 attestation alone is
insufficient for any of them: financial (annual audit by the customer
or a nominated auditor), security (annual at customer's option, with
on-cause audits triggered by security incidents, regulatory inquiries,
or material changes in provider operations), and regulatory
cooperation (audits on demand when the customer's regulator requires
provider-specific evidence). Provider cooperation is at no additional
cost beyond reasonable out-of-pocket reimbursement.

The fallback accepts auditor selection from a list reasonably
acceptable to provider, provided NDAs cannot prevent regulatory
disclosure and findings can be shared with the customer's own
regulators on demand. We do not fall back on the on-cause audit right
or on regulatory cooperation.

## 5. Indemnity caps

Mutual symmetric caps with defined exclusions are the customer-side
default. The cap should reflect actual exposure if the provider fails
— typically 24 months of fees for infrastructure deals, longer for
mission-critical — with the same dollar cap on both sides absent
specific accepted asymmetry. Fraud and wilful misconduct universally
carve out (settled law in England, US, and most major jurisdictions);
IP indemnity super-caps above the general cap (often 2–3× or
uncapped); confidentiality breach is a frequent customer-side super-
cap ask given regulatory-fine exposure.

The fallback accepts asymmetric customer-favourable caps where the
customer's indemnity is genuinely narrower (e.g., AUP violations only)
against a provider indemnity covering infrastructure failures, IP
claims, and data security breaches. We do not fall back on uncapped
customer indemnity or on IP infringement at the general cap level.

## 6. IP ownership

Beyond model/weight ownership (§2): each side keeps its background
IP, the customer owns foreground IP its workloads produce, the
provider owns foreground IP its services produce, and derivative
works default to the side whose IP was the substantial basis. The
"improvements to provider services" clause must be narrowed to
genuinely generic feedback (bug reports, voluntarily-shared
benchmarks, formal enhancement requests) and exclude operational data
from the customer's workload runs — that data reveals the customer's
own optimisations and failure modes and cannot be absorbed by default.

The fallback accepts provider-side telemetry only on per-data-type
opt-in, and publicity rights only on prior written consent before
naming the customer in case studies, press releases, or website
logos. We do not fall back on provider ownership of customer-workload
foreground IP.

## 7. Export-control carve-outs

Each side is responsible for its own compliance with the export-
control regimes applicable to its own operations — mutual indemnity,
mutual reps. The provider warrants that its technology is not on a
restricted list at provision time and notifies the customer of
subsequent classification changes (e.g., new EAR Category 3 or 4
restrictions affecting AI chips); the customer warrants its use will
not violate controls applicable to its own operations.

The fallback accepts asymmetric responsibility allocation only where
the underlying classification question is genuinely on the customer's
side (e.g., end-use compliance in a customer-specific jurisdiction).
We negotiate in a cooperation obligation when the customer needs to
apply for a licence and a force-majeure-like termination right if
controls become so restrictive that operations cannot continue under
the contract without violation.

## 8. Termination triggers

Five categories need clarity: material breach (30-day cure for
breaches that admit of cure, immediate termination for those that
don't — repeated SLA failures, security incidents above defined
severity, regulatory disqualification); change of control of either
side (limited to specific defined reasons, not unconstrained
discretion); insolvency and bankruptcy (customer right to terminate
immediately, data return obligations survive); sustained service
failure (cross-reference §3); and termination for convenience
(customer right on defined notice with pro-rata refund of prepaid
amounts and an early-termination fee proportionate to provider's
actual lost margin, not punitive).

The fallback accepts bilateral change-of-control with provider-side
triggers limited to sanctions or named-competitor acquisition with
written notice stating the reason, and accepts financial-condition
suspension only on objective triggers (missed payment after notice
and cure) paired with continued data access for migration.

## 9. Data return and destruction on exit

On termination, customer data and trained models return in the
customer-specified format (not provider-native lock-in) within a
defined window — typically 60–90 days, longer for very large model
artefacts requiring physical transfer — with provider personnel
cooperation during transition and a written certification from a
senior provider officer that all provider-side copies have been
destroyed within a defined period (typically 180 days after
extraction confirmed). Backups and operational caches need explicit
treatment, with deletion windows tied to operational-copy deletion and
legal-hold exceptions notified to the customer and scope-limited.

The fallback accepts provider-native formats only where conversion is
straightforward and tooling is contractually provided, and accepts
extended retention beyond the 180-day window only where specific
legal-hold requirements compel it. The customer retains its own
copies for post-termination compliance windows; that right is
preserved in the same clause.

## 10. Bias and Responsible AI

Provider commitments must be named, not generic-laws-only: bias
testing and Responsible AI policies disclosed and updated on material
change; provider cooperates with the customer's own bias testing and
audit; provider notifies the customer of incidents at the provider's
level (e.g., model misuse) that could affect the customer's users;
and the provider commits to specific cooperation under emerging AI
regulations (EU AI Act, similar UK / US / UAE frameworks).

The fallback accepts a defined good-faith renegotiation mechanism
when material regulatory changes occur, with a termination right if
good-faith negotiation fails to produce agreement on a material
regulatory question within a defined window. Drafting must remain
flexible enough to absorb regulatory developments without constant
amendment.

## 11. Regulatory cooperation

Cooperation obligations must be named, not "comply with applicable
laws". Specific commitments: support for the customer's data-
protection reviews including DPIAs, regulator inquiries, and data-
subject requests; advance notice of law-enforcement requests for
customer data, subject only to lawfully-imposed gag orders;
cooperation with audits required by the customer's regulators; and
named DPA obligations rather than a generic Article 28 reference.

The fallback accepts regulated-industry tailoring as an addendum
rather than embedded clauses for clauses tied to specific regimes
(DORA in EU, UK operational-resilience equivalent, HIPAA business-
associate frameworks). We do not fall back on the advance-notice
obligation for law-enforcement requests where lawful disclosure is
permitted.

## 12. Pricing and fee escalation

Escalation is capped at a defined annual percentage with a known
formula disclosed in the contract — often 3% or CPI (whichever is
lower) for stable infrastructure deals, higher caps acceptable in
genuinely volatile early-stage GPU markets — with year-over-year
limits to prevent jump-pricing. Renewal pricing must be tied to the
same in-term escalation formula, not "provider's then-current
published rates", with a customer right to terminate without early-
termination fee at renewal if pricing exceeds a defined ceiling.

The fallback accepts asymmetric formula handling where genuine cost
volatility justifies it (hardware-cost pass-through with audit rights
as the trade-off, for example), provided that any such asymmetry is
bounded by the customer's right to challenge the formula's
application during in-term reviews. Currency is denominated in the
customer's preferred currency with no FX exposure imposed on the
customer.

## 13. Dispute resolution

International compute deals are arbitration deals, not court
litigation. For UK-based customers transacting with US-based
providers: London-seated under LCIA Rules with English law as
governing law, three-arbitrator tribunals above a defined threshold,
and a defined procedure for emergency and interim relief allowing
court injunctive applications without arbitration waiver. For UAE /
GCC sovereign customers: DIFC- or ADGM-seated under DIFC-LCIA or
similar; Singapore-seated under SIAC as the default fallback if
neither side wants London.

Confidentiality of proceedings, awards, and enforcement disclosure is
preserved by default, with narrow exceptions only for genuine
collateral-estoppel applications. Mutual injunctive carve-outs for
genuine emergencies (data breach, IP infringement actively occurring)
are uncontroversial and explicit, drafted so that going to court for
those limited purposes is not a waiver of the arbitration clause more
broadly.

---

## Catch-all guidance

For clauses not covered above, apply the materiality test: does
this clause shift risk, financial exposure, or commercial control
between the parties? If yes, treat it as warranting a position and
fallback in the same shape as the categories above. If no —
administrative mechanics, notice provisions, defined-term consistency,
formatting — accept what the provider has drafted unless it is
structurally problematic.

When in doubt, flag to the partner. The playbook is a starting point,
not an exhaustive list of every position the customer might take.
The lawyer's judgement on the specific deal in front of them beats
the playbook on edge cases — and the playbook should be updated when
the lawyer's judgement reveals a position the playbook should have
but doesn't.
