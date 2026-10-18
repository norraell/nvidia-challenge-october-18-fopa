# Evaluation

Status: ok
Generated: 2026-10-18T14:54:44Z
Inputs: artifacts

## Case studies

| Case | Classification | Run | Question |
| --- | --- | --- | --- |
| [case-success-1](cases/case-success-1.md) | success | `run-20261018T144825Z-q01-entomology` | How does the historical Britannica entry on ENTOMOLOGY define and divide the subject, compared with the modern Wikipedia article? Quote both sources. |
| [case-success-2](cases/case-success-2.md) | success | `run-20261018T144825Z-q02-escheat` | Compare how Britannica and Wikipedia explain ESCHEAT: who receives the property and under what conditions. Cite the exact sentences. |
| [case-success-3](cases/case-success-3.md) | success | `run-20261018T144825Z-q06-buttress-image` | This image is a crop from a Britannica page. Which entry is it? Find that entry in the saved artifacts and compare it with its matched Wikipedia article. |
| [case-failure-1](cases/case-failure-1.md) | failure | `run-20261018T144825Z-q03-buttress` | What does the Britannica entry on BUTTRESS say about the purpose of a buttress, and does the Wikipedia article agree? Quote the evidence. |
| [case-failure-2](cases/case-failure-2.md) | failure | `run-20261018T144825Z-q04-oratory` | Compare the Britannica treatment of ORATORY with the Wikipedia article. Which terms does each source use that the other does not? |
| [case-failure-3](cases/case-failure-3.md) | failure | `run-20261018T144825Z-q05-huguenots` | How does Britannica explain the origin of the name HUGUENOTS, and what does Wikipedia say about the same question? |

## Reproduce the run

```sh
uv sync --locked
cp .env.example .env  # then set your own keys and URLs
uv run nemotron-challenge doctor --offline
uv run nemotron-challenge data fetch
uv run nemotron-challenge run extract
uv run nemotron-challenge run match
uv run nemotron-challenge run compare
uv run nemotron-challenge run agent
uv run nemotron-challenge run site
uv run nemotron-challenge run evaluate
uv run pytest
```

Code revision: `5dfff33923dfd512ae4cde9794bc5f634f42341e` (git rev-parse HEAD).
Working tree clean: False.
Python: 3.12.13.
Packages: httpx 0.28.1, pydantic 2.14.1, python-dotenv 1.2.4, lancedb 0.40.0, pyarrow 21.0.0, huggingface-hub 2.2.0.

| Role | Model | Revision |
| --- | --- | --- |
| Page extraction | nvidia/nemotron-3.5-parse | shared endpoint |
| Embedding | nvidia/llama-nemotron-embed-vl-1b-v2 | 582e3bf72aee355e3c59ed89de53543c5b0657ee |
| Reranking | nvidia/llama-nemotron-rerank-vl-1b-v2 | b8a9987b05b75db5ad949c825cbcbf6eb7c48b5a |
| Hermes reasoning | nvidia/Nemotron-3.5-Super-VL | Token Factory |

Data revisions:

- britannica:
  - dataset: NationalLibraryOfScotland/encyclopaedia_britannica_illustrated
  - revision: 309f765b1ecc83e0a7f7762e44b4a927a7555443
  - manifest_sha256: 779542e078756874f23fa6971d7d8a2d8635ad6d9d9484e1deb607d94a28e396
  - source_file_sha256: 08f167015db23cb027995b2b6a6bc953b01d7c1ddf667de950465cc2b601af5c
  - sample_size: 100
  - selection:
    - method: random_without_replacement
    - seed: 20261016
    - sort: source_row_index
- wikipedia:
  - dataset: wikimedia/structured-wikipedia
  - revision: 417c267bb457fa645c22eb3b5c77764963194c70
  - access: shared BM25 API over the pinned snapshot

Retrieval service:

- status: smoke record present
- checked_at: 2026-10-18T12:43:31.728326+00:00
- models: {'id': 'nvidia/llama-nemotron-embed-vl-1b-v2', 'revision': '582e3bf72aee355e3c59ed89de53543c5b0657ee', 'role': 'embedder'}, {'id': 'nvidia/llama-nemotron-rerank-vl-1b-v2', 'revision': 'b8a9987b05b75db5ad949c825cbcbf6eb7c48b5a', 'role': 'reranker'}
- precision: bfloat16
- backend: torch_cuda
- weights_verified: True

Hermes versions in runs: Hermes Agent v0.19.0 (2026.7.20); stage loop via ChatClient.
Super model ids in runs: nvidia/Nemotron-3.5-Super-VL.

## Results

- pages_by_status:
  - blank: 3
  - failed: 2
  - illegible: 1
  - ok: 94
- entries: 270
- matches_by_status:
  - matched: 22
  - no_candidates: 12
  - rejected: 226
  - skipped: 10
- compare:
  - method: token_log_ratio_min_3x_entry_length
  - pairs_used: 22
  - exclusions: 0
  - terms: 210
- runs_by_label:
  - failure: 4
  - success: 10

## Limits

- Fixture tests prove the setup. They do not prove OCR accuracy or retrieval quality.
- Automated checks compare citation ids and quotes with saved records. They do not verify factual claims.
- The success or failure label comes from the team's review in each run record, not from the checks.
- Uncertainty-claim detection is a phrase rule. A reviewer must confirm it against the evidence.
- Some selected cases fail evidence checks: citation_quotes. See each case study.
