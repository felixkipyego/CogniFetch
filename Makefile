.PHONY: eval test

# Runs the golden eval set against the live orchestrator graph. Needs the
# dockerized stack up (Postgres/pgvector, MinIO, Redis) and a real LLM key —
# see eval/README.md.
eval:
	python -m app.evals.run

test:
	pytest
