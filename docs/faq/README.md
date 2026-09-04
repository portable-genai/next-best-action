# FAQ index

Answers to the questions different teams ask when evaluating, adopting, or reviewing this
repository (`next-best-action` Next-Best-Action) as a common base. Each file is written for a specific
audience; skim the one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [features-faq.md](features-faq.md) | Product / compliance / delivery | what the agent does per customer, what is deterministic vs LLM, and the boundary with sibling platform systems |
| [security-faq.md](security-faq.md) | AppSec / security review | server-side identity, tenant isolation, boundary redaction, secrets, supply chain, the audit chain |
| [compliance-faq.md](compliance-faq.md) | Compliance / MLRO / model risk | consent, PII packs, maker-checker, residency, model-risk evidence |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | no-lock-in, the four profiles, on-prem / sovereign exit, open-format export |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rename, upstream fixes, extension points, versioning |

`next-best-action` is the **only per-customer** marketing system in the catalog, so its data-protection,
tenancy and consent controls are load-bearing (unlike the broader-audience marketing repos
`market-intelligence`..`performance-marketing-optimisation`, which handle no customer PII). These FAQs deliberately do **not** re-document
capabilities owned by sibling systems in the
[catalog](https://github.com/portable-genai). Where a concern belongs to another
repo (the guardrail gateway, the governed knowledge base, the eval gate, the human-review
console, the marketing-compliance governor), the FAQ points at it and explains the boundary
rather than duplicating it. See [features-faq.md](features-faq.md) for the full "what this repo
owns vs what it integrates" map.
