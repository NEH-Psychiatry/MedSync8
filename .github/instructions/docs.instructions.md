---
applyTo: "**/*.md,docs/**"
---

# Documentation Rules

- Style basis: AMA Manual of Style (11th ed.). Title Case on headings per NEH convention (articles, coordinating conjunctions, and prepositions of four or fewer letters lowercase unless first or last word).
- Serial (Oxford) comma always. Active voice default. Target 15–20 words average sentence length.
- JCAHO Do Not Use list enforced in any clinical text: U → unit, QD → daily, HS → bedtime, SC/SQ → subcutaneous, D/C → discharge or discontinue, cc → mL, µg → mcg. No trailing zeros; leading zeros required (0.5, never .5).
- Person-first language default (person with SUD; died by suicide). No possessive eponyms (Alzheimer disease).
- Drug names: generic lowercase; brand capitalized in parentheses — sertraline (Zoloft).
- Never paste clinical excerpts, patient details, dates of service, or payer identifiers into documentation. Synthetic examples only. This applies to `corpus/` reference documents, `docs/USER_GUIDE.md` examples, and MAC inquiry drafts.
- The corpus READMEs and `KEY_POINTS.md` describe public federal regulation text; keep regulatory citations, section numbers, and governing dates exact. Flag ambiguity with `[REVIEW: ...]` rather than silently rewriting.
- Billing documentation must keep the decision-support disclaimer and cite CMS sources (MLN909432, CMS-1832-F, MM14315) where thresholds or rates are stated; label estimated rates as estimates and never present a crosswalk-derived figure as verified.
- Command examples in README, RUNBOOK, `CLAUDE.md`, and the user guide must match what actually runs in this repository — verify against CI and package scripts before editing.
- Clinical content editing safety: preserve clinical scope, prescribing authority, supervision requirements, licensure language, signature blocks, regulatory citations, and governing dates exactly. Flag ambiguity with `[REVIEW: ...]` rather than silently rewriting.
- Every doc change that alters user-facing or operational behavior gets a `CHANGELOG.md` entry.
