"""Tokenizing and quote lookup shared by the compare stage and the agent tools."""
from __future__ import annotations

import re

# Standard English stop words (stdlib list in code)
STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
})


def tokenize(text: str) -> list[str]:
    """Normalize and tokenize text: lowercase, ſ->s, split on non-letters, drop < 3 chars & stopwords."""
    norm = text.lower().replace("ſ", "s")
    raw_tokens = re.findall(r"[a-z]+", norm)
    return [t for t in raw_tokens if len(t) >= 3 and t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for quote extraction."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    # Split on sentence terminals followed by space
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return [s.strip() for s in sentences if s.strip()]


def find_quote(text: str, term: str) -> str:
    """Find the first sentence containing the term as a whole word."""
    sentences = split_sentences(text)
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    for s in sentences:
        if pattern.search(s):
            return s
    return sentences[0] if sentences else ""
