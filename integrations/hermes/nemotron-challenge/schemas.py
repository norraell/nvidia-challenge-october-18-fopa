"""Tool schemas. The model reads these to decide when to call each tool."""

BRIT_SEARCH = {
    "name": "brit_search",
    "description": (
        "Find Britannica entries by topic or word. Returns entry_id, headword, page_id, the first "
        "300 characters, and quality flags. The result names the method that ran (embedding or keyword)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 500,
                      "description": "Words or a short phrase to find."},
            "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5,
                  "description": "Number of entries to return."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

BRIT_ENTRY = {
    "name": "brit_entry",
    "description": (
        "Read one Britannica entry in full: normalized text, raw OCR text, headword, page_id, "
        "text blocks, quality flags, crop path, and the volume record from the source manifest."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entry_id": {"type": "string", "pattern": "^e[0-9]{4}-[0-9]{2}$",
                         "description": "Entry ID such as e0013-01."},
        },
        "required": ["entry_id"],
        "additionalProperties": False,
    },
}

WIKI_ARTICLE = {
    "name": "wiki_article",
    "description": (
        "Read one page of a Wikipedia article. Returns revision_id, url, text, and next_offset. "
        "Call again with next_offset to read more. The tool rejects a revision that differs from the match record."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page_id": {"type": "string", "pattern": "^[0-9]{1,20}$", "description": "Wikipedia page ID."},
            "offset": {"type": "integer", "minimum": 0, "default": 0,
                       "description": "Character offset where the page starts."},
        },
        "required": ["page_id"],
        "additionalProperties": False,
    },
}

CHALLENGE_COMPARE = {
    "name": "challenge_compare",
    "description": (
        "Compare one Britannica entry with its matched Wikipedia article. Returns the match record "
        "(status, reason, rerank margin), the matched article reference, the vocabulary terms found in "
        "both texts with quotes, and the first 1,500 characters of each text. Call this before any "
        "factual answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entry_id": {"type": "string", "pattern": "^e[0-9]{4}-[0-9]{2}$",
                         "description": "Entry ID such as e0013-01."},
        },
        "required": ["entry_id"],
        "additionalProperties": False,
    },
}
