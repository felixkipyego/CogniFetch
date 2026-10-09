# Eval corpus (golden set, Phase 3)

Fixtures for the evaluation harness in `app/evals/` (see `ENHANCEMENT_ROADMAP.md` Phase 3). `python -m app.evals.run` (or `make eval`) runs this set against the live orchestrator graph and prints a scorecard — see the top-level README's "Evaluation" section for current scores.

## Contents

- `corpus/*.pdf` — 4 short synthetic documents, each 2 pages, covering a distinct fictional topic (HR policy, a cloud SLA, a SaaS FAQ, a sustainability report). Generated, not sourced from the web, so there are no licensing concerns about committing them to a public repo. Each document's facts are deliberately unambiguous and page-scoped, so a correct retrieval/citation should point at one specific page.
- `qa_pairs.json` — 25 question/expected-answer/expected-citation triples:
  - `*-01` through `*-05` per document (20 total): single-fact lookups, each citing exactly one page.
  - `out-of-corpus-01`: a general-knowledge question with no plausible connection to any uploaded document — should route to `web_research`, not get an ungrounded RAG answer.
  - `out-of-corpus-02`: a harder grounding trap — the company name (Northwind) IS in the corpus, so the supervisor should route to `rag`, but the handbook excerpt never covers the topic asked (dress code). Tests that RAG retrieves, finds nothing on-topic, and refuses rather than inferring a plausible-sounding answer. This directly targets the grounding gap found while measuring the Phase 0 baseline.
  - `cross-doc-01/02/03`: real multi-document comparison questions, each citing two documents, scored by the `multi_doc_synthesis` route added in Phase 2. (The original Phase 0 placeholder here, `cross-doc-01`, was flagged as "not gradable yet" since that sub-agent didn't exist; it does now, so these are real graded cases.)

Each case's schema: `id`, `documents` (filenames the answer should cite, `[]` for out-of-corpus), `question`, `expected_answer`, `expected_citations` (list of `{document, pages}`).

## Why these particular documents

Each page contains 3-4 standalone facts with specific numbers (percentages, dollar amounts, day counts), so an automated scorer can check "did the answer contain the expected number" without fuzzy matching, and "did the citation point at the right page" without ambiguity about which page a fact lives on.

## Regenerating

The PDFs were generated with `fpdf2` from a one-off script (not checked into the repo, since it's not part of the app). If the corpus ever needs to change, regenerate deterministically rather than hand-editing the PDFs, and update `qa_pairs.json` to match.

## Status

Golden set for Phase 3, 25 pairs (within the roadmap's 20-40 target). Scored on four dimensions by `app/evals/`: retrieval precision/recall (deterministic, page-overlap based), answer correctness, faithfulness, and citation accuracy (all three via LLM-as-judge, same structured-output pattern as `grade_documents`).
