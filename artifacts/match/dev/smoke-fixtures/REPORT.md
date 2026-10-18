# Match report

Relevance scores from BM25, the embedder, and the reranker show that two texts treat the same subject. They do not establish factual agreement between Britannica and Wikipedia.

Method: `m1-tau=2.1-delta=0.4`. Elapsed: 12.2 s.

## Coverage

- Entries: 5
- Pages: 3, with at least one match: 0
- By status: rejected=5
- By kind: continuation: rejected=1; entry: rejected=3; plate: rejected=1
- Matches found only by the content-words query: 0

## Omissions

| entry | headword | status | top candidate | bm25 | cosine | logit |
|---|---|---|---|---|---|---|
| e0013-01 | ABACUS | rejected | Abacus | 49.119 | 0.475 | -0.707 |
| e0013-02 |  | rejected | Mechanical calculator | 21.507 | 0.293 | -5.401 |
| e0104-01 | BAROMETER | rejected | Barometer | 56.674 | 0.447 | -4.402 |
| e0104-02 |  | rejected | Edward Nairne | 29.896 | 0.280 | -7.779 |
| e0115-01 | CALORIC | rejected | Caloric theory | 61.498 | 0.467 | -4.117 |

## Repeated article selections

### Expected (0)
- none

### Suspicious (0)
- none

## Failed calls

- none
