"""Match stage: turn each Britannica entry into a verified Wikipedia match or a recorded rejection.

A relevance score from BM25, the embedder, or the reranker never proves factual
agreement between the two sources. It says only that the texts are about the same subject.
"""
