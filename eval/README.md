# Eval corpus (Phase 0 baseline)

Frozen fixtures for the evaluation harness planned in Phase 3 of the enhancement roadmap. Nothing here is wired into the app or test suite yet — this is just the fixed input data so that later graph/prompt changes (Phases 1-2) have a stable baseline to diff against, rather than re-picking documents and questions after the fact.

## Contents

- `corpus/*.pdf` — 4 short synthetic documents, each 2 pages, covering a distinct fictional topic (HR policy, a cloud SLA, a SaaS FAQ, a sustainability report). Generated, not sourced from the web, so there are no licensing concerns about committing them to a public repo. Each document's facts are deliberately unambiguous and page-scoped, so a correct retrieval/citation should point at one specific page.
- `qa_pairs.json` — 18 question/expected-answer pairs referencing those documents, plus:
  - `out-of-corpus-01`: a question with no answer in any document, to check the agent correctly says so instead of hallucinating.
  - `cross-doc-01`: a comparison question spanning two documents, flagged as a Phase 2 multi-document-synthesis test case rather than a single-fact grading case.

## Why these particular documents

Each page contains 3-4 standalone facts with specific numbers (percentages, dollar amounts, day counts), so an automated scorer can check "did the answer contain the expected number" without fuzzy matching, and "did the citation point at the right page" without ambiguity about which page a fact lives on.

## Regenerating

The PDFs were generated with `fpdf2` from a one-off script (not checked into the repo, since it's not part of the app). If the corpus ever needs to change, regenerate deterministically rather than hand-editing the PDFs, and update `qa_pairs.json` to match.

## Status

Candidate set for Phase 0. Phase 3 expands this to the full 20-40 pair golden set with automated retrieval precision/recall, LLM-as-judge faithfulness scoring, and citation-accuracy checks — see `ENHANCEMENT_ROADMAP.md`.
