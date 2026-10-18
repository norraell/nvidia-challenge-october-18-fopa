#!/usr/bin/env sh
# Minimal live check of the embedder and reranker endpoint.
# Reads RETRIEVAL_BASE_URL and RETRIEVAL_API_KEY from .env. Never prints the key.
set -eu
set -a; . ./.env; set +a
AUTH="Authorization: Bearer ${RETRIEVAL_API_KEY}"
EMBED=nvidia/llama-nemotron-embed-vl-1b-v2
RERANK=nvidia/llama-nemotron-rerank-vl-1b-v2

echo "== ready"
curl -sS --fail -H "$AUTH" "$RETRIEVAL_BASE_URL/../ready" | jq '{status, production: .runtime.production, gpu: .runtime.gpu, precision: .runtime.precision}'

echo "== models"
curl -sS --fail -H "$AUTH" "$RETRIEVAL_BASE_URL/models" | jq '.data[] | {id, revision, role, dimensions}'

echo "== embeddings (query + document)"
curl -sS --fail -H "$AUTH" -H 'Content-Type: application/json' "$RETRIEVAL_BASE_URL/embeddings" \
  --data "{\"model\":\"$EMBED\",\"input_type\":\"query\",\"input\":[\"volcano eruption and lava\"]}" \
  | jq '{model, dimensions, normalized, n: (.data|length), first3: .data[0].embedding[:3]}'

echo "== rerank"
curl -sS --fail -H "$AUTH" -H 'Content-Type: application/json' "$RETRIEVAL_BASE_URL/rerank" \
  --data "{\"model\":\"$RERANK\",\"query\":\"volcano eruption and lava\",\"documents\":[\"Mount Etna is an active volcano in Sicily.\",\"The Treaty of Westphalia was signed in 1648.\",\"Basalt forms when lava cools quickly.\"]}" \
  | jq '{model, score_type, results}'
