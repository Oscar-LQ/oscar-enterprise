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

---

## Preliminary note

The deals this playbook applies to are large compute-capacity
arrangements — multi-year reservations of GPU clusters or other
specialised AI infrastructure, typically with provider-favourable
default drafting because the providers are oligopolistic and the
contracts originate from their templates. Our instinct on every
clause is to read what the provider has proposed and ask: would a
sophisticated customer with sovereignty concerns, regulatory
exposure, and a multi-year operational dependency accept this without
a fight? Where the answer is no, we push back.

We are negotiating on behalf of a customer whose business depends on
the compute we are buying. Walking away is genuinely on the table on
walk-away points — we are not posturing. Where we mark a fallback,
we mean it: that is the position we would actually settle at if the
provider holds firm.

## 1. Data residency and sovereignty

Our position is that customer data — including all inputs we send to
the compute environment, all outputs the environment produces, and
all derivatives the provider generates from operating our workloads
— stays in jurisdictions we name and approves before any cross-border
movement. The starting list is typically the customer's primary
jurisdiction plus any explicitly contracted secondary regions for
disaster recovery; we are not interested in the provider's "global
footprint" being a reason data ends up wherever its capacity is
cheapest that month. For sovereign-AI customers (UAE, Saudi, Singapore,
similar), the data-residency clause carries the regulatory weight of
the entire deal — UAE PDPL, Singapore PDPA, sector-specific
frameworks all require provable in-country processing, and "best
efforts" or "commercially reasonable efforts" language fails that
test. We want a hard commitment that the workloads run in named
regions and that the provider's own access (for support, monitoring,
incident response) flows through named-region staff or via documented
egress paths the customer has approved.

The fallback we can live with is a hard commitment for primary
production workloads with a named-region requirement, plus a defined
exception process for short-duration support access by named senior
provider personnel, with logging and customer notification. We do not
fall back on disaster recovery — DR sites are explicitly contracted,
not at the provider's discretion.

The walk-away is any clause that lets the provider relocate workloads
"as required for capacity management" or "to meet operational needs"
without customer consent. That is operationally indistinguishable from
"data resides wherever we want" and defeats the regulatory purpose
of the residency commitment.

## 2. Model and weight ownership

This is where AI-compute MSAs differ from generic cloud contracts and
where provider templates are most aggressive. The provider will often
draft so that any model trained or fine-tuned on its infrastructure is
"derivative work" of provider technology, that customer-fine-tuned
weights are "intermediate outputs" the provider has rights to, or that
the provider may use customer-trained models to "improve the service"
unless the customer opts out. None of that is acceptable. Our position
is that the customer owns all weights and models trained on its data,
all fine-tuning artefacts of base models the customer has licensed,
and all outputs the customer's workloads produce, with no provider
licence-back, no improvement-of-service exception, and no claim that
running on the provider's hardware creates any shared IP interest.
Provider IP — base models the provider has licensed to the customer,
provider-side software, monitoring tools, the orchestration stack —
remains the provider's, but the line between provider IP and customer
IP needs to be drawn explicitly in the contract, not left to default
copyright reasoning.

We will accept a narrow licence to the provider for the purpose of
operating the service — i.e., the provider may load weights into
GPUs, copy them between nodes for parallelism, retain them in
operational caches — but only for the term and only for the operation
of the customer's workloads. Any retention beyond the term, any
provider use for model improvement, any access by provider personnel
for purposes other than incident response, requires separate
written consent.

Walk-away is any clause framing customer-trained models as joint IP,
provider-licensed-back IP, or "service improvement" inputs. These
clauses are sometimes drafted with seemingly innocuous language
("provider may use aggregated learnings") but the practical effect is
loss of control over the customer's most valuable asset on the
contract — the trained model itself.

## 3. SLA tiers

The provider's standard SLA is usually a 99.9% uptime target measured
on a per-region rolling-monthly basis with service credits as the sole
remedy. For a multi-year compute reservation that the customer's
business depends on, that is not a serious commitment. Our position
asks for tiered SLAs with the highest tier (mission-critical
workloads) at 99.95% or 99.99% measured per-availability-zone, with
defined response and resolution times for incidents at each severity
level, with service credits scaled proportionally to the workload's
business impact (not capped at a small percentage of monthly fees),
and with a sustained-failure exit right that lets us terminate
without penalty if the provider misses targets across consecutive
measurement periods.

Capacity reservations need their own treatment in the SLA. If the
customer has reserved a fixed GPU cluster, the SLA must cover both
availability (the cluster is up) and capacity (the cluster delivers
the contracted compute throughput). Providers sometimes draft SLAs
that cover availability but not throughput — a cluster that is "up"
but running at half capacity is not what the customer is paying for.
The throughput commitment needs to be quantified in operational terms:
TFLOPS sustained over a measurement window, jobs-per-hour at a defined
workload profile, or similar. Vague language like "burstable" or
"best efforts" fails on this point.

Fair-use clauses purportedly limiting "abuse" are usually drafted
broadly enough to give the provider unilateral throttling rights. We
push back: any throttling needs an objective trigger (e.g.,
contractually defined load thresholds), prior notice, and a defined
remediation path. We will accept a narrow exception for the genuine
abuse case (workloads that violate AUP, attempt to interfere with
other customers, etc.) but only with notice and a cure period for
ambiguous cases.

The walk-away is service credits as sole remedy combined with no
exit right on sustained failure. That combination means a provider
who stops performing is contractually fine — they pay credits, the
customer gets nothing useful, and the customer cannot leave. We will
not sign a multi-year reservation on those terms.

## 4. Audit rights

Audit rights need to cover three distinct concerns: financial (are
fees calculated correctly), security (is the provider doing what it
said about how customer data is handled), and regulatory cooperation
(can the customer satisfy its own regulators by getting evidence
about provider practices). Providers typically resist all three by
offering a single annual "SOC 2 attestation report" as the substitute
for audit. SOC 2 is useful but not sufficient — it covers what the
provider chose to scope into the audit, often excludes the
customer's specific workload, and gives no insight into incidents
that fall outside the audit window.

Our position is the customer has the right to audit on each of the
three concerns: an annual financial audit by the customer or a
nominated auditor; security audits at the customer's option (usually
annual but with a right to additional on-cause audits triggered by
defined events such as a security incident, regulatory inquiry, or
material change in provider operations); and regulatory audits on
demand when the customer's regulator requires evidence the customer
cannot produce from its own records. The provider must cooperate
with all three at no additional cost beyond reasonable
reimbursement of out-of-pocket expenses.

Third-party auditor access is a frequent sticking point. The
provider wants to control which auditors can be used (their own
panel) and to require NDAs that effectively prevent the customer
from using audit findings for its own regulatory purposes. We push
back: customer chooses the auditor from a list reasonably acceptable
to provider, NDAs cannot prevent regulatory disclosure, and the
customer must be allowed to share findings with its own regulators
on demand.

Walk-away is no on-cause audit rights and no regulatory cooperation.
Without those, the customer cannot satisfy its own regulators when
they ask hard questions, and that is an unacceptable operational
risk.

## 5. Indemnity caps

The default in provider templates is asymmetric: the provider's
indemnity to the customer is capped (often at 12 months of fees),
the customer's indemnity to the provider is uncapped, and several
high-risk categories carve out of the provider's cap entirely
(typically anything related to the provider's negligence, breach of
core obligations, or IP indemnity). Symmetric mutual caps with
defined exclusions are the customer-side default position. The cap
should be a multiple of fees that reflects the customer's actual
exposure if the provider fails — usually 24 months for
infrastructure deals, sometimes longer for mission-critical
workloads — and should be the same dollar cap on both sides unless
there is a specific reason for asymmetry that the customer accepts.

Exclusions from the cap need to be written carefully. Fraud and
wilful misconduct universally carve out (this is settled law in
England, US states, and most major jurisdictions; the contract should
just acknowledge it). IP indemnity should super-cap above the
general cap — the customer's exposure to a third-party IP claim
based on provider technology is potentially uncapped, and the
provider needs to backstop that with a higher indemnity ceiling
(often 2–3× the general cap, sometimes uncapped for the IP head).
Confidentiality breach is a frequent customer-side request to
super-cap as well — the consequences of a provider leaking customer
data can be regulatory fines well exceeding fee-multiples.

We accept asymmetric customer-favourable caps when the customer's
side of the indemnity is genuinely narrower in scope than the
provider's (e.g., customer indemnifies for AUP violations only;
provider indemnifies for infrastructure failures, IP claims, and
data security breaches). We do not accept asymmetric
provider-favourable caps without specific justification.

The walk-away is uncapped customer indemnity (especially when the
provider's is capped), or a cap structure that puts IP infringement
at the general cap level — that combination means the customer is
absorbing more risk than the contract is generating in value.

## 6. IP ownership

Beyond model/weight ownership (covered separately in §2), the
broader IP allocation in the MSA has three pieces: foreground IP
(developed during the engagement), background IP (each side's
pre-existing IP), and derivative works. The customer-side default
is that each side keeps its background IP, the customer owns
foreground IP that the customer's workloads produce, the provider
owns foreground IP that the provider's services produce, and
derivative works default to the side whose IP was the substantial
basis for the derivative.

Provider templates often draft with a broad "improvements to provider
services" clause that captures any feedback, error reports, or
operational data the customer generates while using the service.
This is a problem — operational data from running customer
workloads can include sensitive information about how the
customer's models perform, what optimisations the customer has
discovered, what failure modes are revealed by specific use patterns.
A clause that grants the provider rights to use this for "service
improvement" is effectively a licence to absorb the customer's
operational know-how into the provider's competitive moat.

We push back by narrowing the improvements clause to genuinely
generic feedback (bug reports against documented features,
performance data the customer voluntarily shares for benchmarking,
formal enhancement requests) and excluding operational data from
the customer's workload runs. Where the provider wants telemetry
from the customer's environment for service improvement, the
customer needs to opt in deliberately on a per-data-type basis,
not have it captured by default.

Publicity rights — the provider's right to name the customer in
case studies, press releases, website logos — are typically a
subordinate concern but worth catching in this section. Default
position: provider needs customer's prior written consent before
naming the customer in any public-facing material. Provider
templates often draft this the other way (customer consents up
front to being named generally), and we routinely flip it.

Walk-away is provider ownership of foreground IP that the
customer's workloads produce, or a broad improvements clause that
captures customer operational data without an opt-in.

## 7. Export-control carve-outs

For sovereign-AI customers and for any customer with operations
across the US-UAE-China triangulation, export controls are a
front-line concern. The MSA needs explicit allocation of
responsibility: who is responsible for ensuring that the technology
being delivered (compute, model access, software) does not violate
US export controls (EAR/ITAR), UK regimes, EU regimes, and the
customer's own jurisdiction's controls. The default position from
provider templates is usually that the customer represents and
warrants compliance, with a broad indemnity to the provider — i.e.,
the customer absorbs all export-control risk regardless of who
introduced the violation.

Our customer-side position is that each side is responsible for
its own compliance with the export-control regimes applicable to
its own operations. The provider warrants that the technology it
provides is not on a restricted list at the time of provision and
that any subsequent classification changes will be notified to the
customer; the customer warrants that its use of the technology
will not violate export controls applicable to the customer's own
operations. Mutual indemnity, mutual reps. The provider does not get
to push the entire compliance burden onto the customer when a
substantial part of the classification question is the provider's
own technology.

Specific clauses we typically negotiate in: a notification
obligation when the provider's technology is reclassified (e.g.,
new restrictions added under EAR Category 3 or 4 affecting AI
chips); a cooperation obligation on the provider when the customer
needs to apply for a licence to use the technology in a specific
jurisdiction; and a force-majeure-like termination right if export
controls become so restrictive that the customer's operations cannot
continue under the contract without violation.

The walk-away is unilateral customer indemnity for export-control
violations of any kind, including those originating from provider
technology classifications outside the customer's control. That
shifts a regulatory risk that should be shared onto a single party.

## 8. Termination triggers

Multi-year compute reservations are operationally hard to exit, so
termination triggers carry weight disproportionate to their drafting
length. Customer-side, we want clarity on five categories: material
breach (with a defined cure period for breaches that admit of cure,
typically 30 days, and immediate termination for material breaches
that do not — repeated SLA failures, security incidents above a
defined severity, regulatory disqualification); change of control of
the provider (customer right to terminate without penalty if the
provider is acquired by a competitor, a sanctioned entity, or a
party the customer cannot do business with for regulatory reasons);
insolvency and bankruptcy (customer right to terminate immediately;
data return and destruction obligations survive termination);
sustained service failure (covered in §3 above, repeated here as a
termination trigger); and termination for convenience (customer
right to exit on a defined notice period, with pro-rata refund of
prepaid amounts and a defined early-termination fee that is
proportionate to the provider's actual lost margin, not punitive).

Provider templates often draft change-of-control as bilateral, which
is fine in principle, but the language frequently lets the provider
terminate on customer change of control "in provider's reasonable
discretion" — which is unconstrained discretion under standard
contract interpretation. Push back: provider's termination on
customer change of control is limited to specific, defined reasons
(sanctions, named-competitor acquisition, etc.) and requires written
notice with the reason stated.

Insolvency clauses sometimes include a provider right to suspend
service "in provider's discretion" if the customer's financial
condition deteriorates. This is a cliff: the provider can effectively
disable the customer's operations on a unilateral judgement about
financial health. Push back: any suspension on financial-health
grounds requires a defined trigger (e.g., missed payment after
notice and cure period) and is paired with continued data access
for the customer to migrate.

The walk-away is no termination right on sustained breach, or a
termination-for-convenience right with a punitive early-termination
fee. Both shift the customer into a position where the contract is
operationally a one-way commitment.

## 9. Data return and destruction on exit

The exit clause is where customer-side counsel earns its fee. On
termination — for any reason, by either side — the customer needs
to be able to extract its data and trained models in a usable
format, on a defined timeline, and to require certified destruction
of provider-side copies thereafter. Provider templates often draft
this minimally: "customer may request a copy of customer data for
30 days post-termination" with no format commitment, no SLA on
delivery, and no destruction certification.

Our position is that the customer's data and the customer's trained
models are returned in the format the customer specifies (not
provider-native lock-in formats), within a defined window (typically
60–90 days post-termination, longer for very large model artefacts
that need physical transfer), with provider personnel cooperation
during the transition (so the customer can spin up workloads on its
new infrastructure without losing production continuity), and with
a written certification from a senior provider officer that all
provider-side copies have been destroyed within a defined period
(typically 180 days after the customer confirms successful
extraction).

Backups and operational caches need explicit treatment. Provider
backup systems often retain data for compliance reasons beyond the
operational lifecycle — that is fine in principle but the customer
needs to know how long, where, and what triggers deletion. The
clause should commit the provider to deleting backups within a
defined window after the operational copies are deleted, except where
specific legal-hold requirements apply (and in that case, the
provider notifies the customer and limits retention to the legal-hold
scope).

The customer's right to retain its own copies of the data for
post-termination compliance windows is also worth catching here —
the customer cannot delete its records of the relationship just
because the relationship has ended.

The walk-away is a termination clause where data return is best-
efforts, format-not-specified, or where the provider can charge an
extraction fee that is effectively punitive for large model
artefacts. That structure traps the customer into renewing the
contract because the cost of leaving is artificially high.

## 10. Bias and Responsible AI

For customers using compute infrastructure to train or deploy AI
models that affect end users (recommendation systems, hiring
decisions, credit decisions, healthcare applications), the MSA
needs to include the customer's visibility into the provider's
Responsible AI practices. This is a relatively new clause category
and provider templates either omit it entirely or address it only
through a generic "compliance with applicable laws" reference.
Customer-side, we want named commitments: the provider's bias
testing and Responsible AI policies are disclosed to the customer
and updated when material changes occur; the provider cooperates
with the customer's own bias testing and audit; the provider
notifies the customer of any incidents at the provider's level
(e.g., model misuse incidents) that could affect the customer's own
users; and the provider commits to specific cooperation obligations
under emerging AI regulations (EU AI Act, similar frameworks under
discussion in the UK, US, UAE).

This category has the practical complication that customer-side
counsel and provider-side counsel are both still working out what
the substance of Responsible AI clauses should be. Drafting needs
to be flexible enough to absorb regulatory developments without
constant amendment. We typically include a defined update mechanism
where the parties commit to negotiate amendments in good faith
when material regulatory changes occur, with a fallback termination
right if good-faith negotiation fails to produce agreement on a
material regulatory question within a defined window.

The walk-away is no Responsible AI commitments at all — that
leaves the customer holding the entire regulatory bag for AI
deployment when the regulatory framework is shifting underneath
both parties. We need shared visibility and shared cooperation.

## 11. Regulatory cooperation

Beyond AI-specific regulation, the broader regulatory cooperation
clause covers data protection (GDPR, CCPA, UAE PDPL, sector-
specific regimes), financial-services regulation where the customer
is regulated (FCA, OCC, monetary authorities), healthcare regimes
(HIPAA, similar), and law-enforcement requests. Provider templates
typically draft this as "provider will comply with applicable laws"
with a side commitment to "reasonable cooperation" with customer's
regulatory obligations. That is too thin.

Our position requires named cooperation obligations: the provider
commits to specific support for the customer's GDPR / equivalent
data-protection reviews, including DPIAs, regulator inquiries, and
data-subject requests; the provider commits to advance notice of
law-enforcement requests for customer data (subject to gag orders
that are themselves lawfully imposed — providers cannot use the
"we received a national security letter we cannot disclose" line
as an excuse to avoid the entire notification structure); the
provider commits to cooperating with customer's audits required by
the customer's regulators; and the provider takes named DPA
obligations rather than a generic Article 28 reference.

For regulated-industry customers, the clause needs to be tailored
to the specific regulatory regime — financial-services customers
need provider obligations under operational-resilience rules
(DORA in EU, similar in UK), healthcare customers need provider
obligations under HIPAA business-associate frameworks. The MSA
either incorporates these directly or attaches them as a regulated-
industry addendum.

The walk-away is a regulatory cooperation clause that is generic-
laws-only with no specific commitments and no advance-notice
obligation on law-enforcement requests. That leaves the customer
unable to satisfy its own regulators when the regulators ask
provider-specific questions, and is an operational risk
disproportionate to the value of the contract.

## 12. Pricing and fee escalation

Multi-year compute reservations have economic mechanics that work
against the customer if not negotiated carefully. The provider
typically draws annual escalation clauses that compound aggressively
— a 5% annual escalator on a 5-year contract is a 27% effective
price increase by year 5, and on a 10-year contract is a 63%
increase. Provider templates often draft escalators as "CPI plus a
margin" or "provider's then-current rates", which gives the
provider unilateral repricing power.

Our position caps escalation at a defined annual percentage (often
3% or CPI, whichever is lower, for stable infrastructure deals;
higher caps may be acceptable for early-stage GPU markets where
hardware costs are genuinely volatile) with a known formula
disclosed in the contract, with year-over-year limits that prevent
jump-pricing if the formula produces a large increase in any single
year.

Renewal pricing is a separate concern. Provider templates often
make renewal prices "provider's then-current published rates",
which means the provider can set renewal economics unilaterally.
We push for renewal pricing tied to the same escalation formula
that governs in-term pricing, with a customer right to terminate
without early-termination fee at renewal if pricing exceeds a
defined ceiling.

Most-favoured-nation clauses are sometimes worth fighting for, and
sometimes not — they are most useful when the customer is large
enough to credibly demand provider parity with peer customers, and
they are very hard to enforce in practice without robust audit
rights. We typically position MFN as a high-value ask in
negotiations to be used as a trade for other priorities, rather
than as a non-negotiable requirement.

Currency and FX handling matters for international deals. The
contract should specify currency, conversion mechanism if
applicable, and which side bears FX risk. Customer-side default is
that fees are denominated in the customer's preferred currency
(usually USD or local sovereign currency for sovereign-AI
customers) with no FX conversion exposure imposed on the customer.

The walk-away is uncapped escalation, "then-current rates" renewal
pricing, or FX risk shifted onto the customer for fees denominated
in provider's preferred currency. The combination is economic
hostage-taking.

## 13. Dispute resolution

International compute deals are almost universally arbitration
deals — court litigation is too slow, too public, and too
jurisdictionally fragmented for multi-billion-dollar
infrastructure agreements. The substantive choices are seat,
governing law, institutional rules, and tribunal composition.

For UK-based customers transacting with US-based providers, we
typically push for London-seated arbitration under LCIA Rules with
English law as governing law, three-arbitrator tribunals for
disputes above a defined threshold, and a defined procedure for
emergency and interim relief that allows the customer to obtain
injunctive relief in court without being deemed to have waived
arbitration. For UAE / GCC sovereign customers, DIFC- or ADGM-
seated arbitration under DIFC-LCIA or similar institutional rules
is often appropriate; Singapore-seated under SIAC is the default
fallback if neither side wants London.

The provider's default is usually New York or Delaware court
litigation with provider's choice of law. We push back on both
counts: court litigation is rejected for the operational reasons
above, and provider-favourable choice of law is rejected because it
biases the substantive interpretation of the contract toward the
provider's domestic norms.

Confidentiality of arbitration is a default we want preserved — the
proceedings should be confidential, the awards should be
confidential, and any disclosure for enforcement should be limited
to what enforcement actually requires. The provider sometimes pushes
for the right to disclose awards in subsequent disputes; we push
back, with narrow exceptions for genuine collateral-estoppel
applications.

Carve-outs for injunctive relief and IP enforcement — both sides
typically want to be able to go to court for emergency injunctive
relief in genuine emergencies (data breach, IP infringement
actively occurring) without going through the full arbitration
process. This is mutual and uncontroversial; the contract just
needs to draft it explicitly so that going to court for these
limited purposes is not a waiver of the arbitration clause more
broadly.

The walk-away is provider-state court litigation with provider's
choice of law and no confidentiality. That combination produces
expensive, public, biased dispute resolution that the customer
cannot win even on substantive merit because of forum bias.

---

## Catch-all guidance

For clauses not covered above, apply the materiality test: does
this clause shift risk, financial exposure, or commercial control
between the parties? If yes, push back on a customer-favourable
position. If no — administrative mechanics, notice provisions,
defined-term consistency, formatting — accept what the provider has
drafted unless it is structurally problematic. The clause category
does not determine the response; the commercial impact does.

When in doubt, flag to the partner. The playbook is a starting
point, not an exhaustive list of every position the customer might
take. The lawyer's judgement on the specific deal in front of them
beats the playbook on edge cases — and the playbook should be
updated when the lawyer's judgement reveals a position the playbook
should have but doesn't.
