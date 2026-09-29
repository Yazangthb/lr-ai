"""One boolean query syntax, rendered for each database.

Syntax (what users and Claude write in config.yaml):
    ("citation graph" OR "citation network") AND (forecast* OR predict*) NOT survey
- Uppercase AND / OR / NOT, parentheses, "quoted phrases", trailing * for prefix matching.
- Adjacent terms without an operator are ANDed.
"""
from __future__ import annotations

OPERATORS = ("AND", "OR", "NOT")
_OPERAND_END = ("TERM", "PHRASE", ")")
_OPERAND_START = ("TERM", "PHRASE", "(", "NOT")


def tokenize(query: str) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    i, n = 0, len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
        elif c in "()":
            raw.append((c, c))
            i += 1
        elif c == '"':
            j = query.find('"', i + 1)
            j = n if j == -1 else j
            phrase = " ".join(query[i + 1 : j].split())
            if phrase:
                raw.append(("PHRASE", phrase))
            i = j + 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in '()"':
                j += 1
            word = query[i:j]
            i = j
            if word in OPERATORS:
                raw.append((word, word))
            elif word.strip("-+|,;"):
                raw.append(("TERM", word.strip(",;")))
    tokens: list[tuple[str, str]] = []
    for t in raw:
        if tokens and tokens[-1][0] in _OPERAND_END and t[0] in _OPERAND_START:
            tokens.append(("AND", "AND"))
        tokens.append(t)
    return tokens


def _join(parts: list[str]) -> str:
    return " ".join(parts).replace("( ", "(").replace(" )", ")")


def to_plain(query: str) -> str:
    """Flatten to plain words for relevance-ranked engines: keep terms and phrases, drop NOT-ed parts."""
    words: list[str] = []
    depth_negated: list[bool] = []  # per open parenthesis: is this group negated?
    negate_next = False
    for kind, val in tokenize(query):
        if kind == "NOT":
            negate_next = True
        elif kind == "(":
            depth_negated.append(negate_next or (bool(depth_negated) and depth_negated[-1]))
            negate_next = False
        elif kind == ")":
            if depth_negated:
                depth_negated.pop()
        elif kind in ("TERM", "PHRASE"):
            negated = negate_next or (bool(depth_negated) and depth_negated[-1])
            negate_next = False
            if not negated:
                w = val.rstrip("*")
                if w and w not in words:
                    words.append(w)
    return " ".join(words)


STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is of on or the their this to using via what which with"
    .split())


def keywords(text: str) -> str:
    """Natural-language query -> space-separated content words (implicitly ANDed by the renderers)."""
    words = [w.strip(".,;:!?()\"'") for w in text.split()]
    return " ".join(w for w in words if w and w.lower() not in STOPWORDS and w.upper() not in OPERATORS)


def to_openalex(query: str) -> str:
    """OpenAlex boolean search: AND/OR/NOT, quotes, parentheses; no wildcards, no commas."""
    parts = []
    for kind, val in tokenize(query):
        if kind == "TERM":
            val = val.rstrip("*").replace(",", " ")
            if val:
                parts.append(val)
        elif kind == "PHRASE":
            parts.append('"' + val.replace(",", " ").replace("*", "") + '"')
        else:
            parts.append(val)
    return _join(parts)


def to_semantic_scholar(query: str) -> str:
    """Semantic Scholar bulk search: + (AND), | (OR), -term (NOT), quotes, parentheses, prefix*."""
    tokens = tokenize(query)
    parts: list[str] = []
    negate = False
    for idx, (kind, val) in enumerate(tokens):
        nxt = tokens[idx + 1][0] if idx + 1 < len(tokens) else None
        if kind == "AND":
            if nxt != "NOT":
                parts.append("+")
            continue
        if kind == "OR":
            parts.append("|")
            continue
        if kind == "NOT":
            negate = True
            continue
        text = f'"{val}"' if kind == "PHRASE" else val
        if negate and kind in ("TERM", "PHRASE", "("):
            text = "-" + text
            negate = False
        parts.append(text)
    return _join(parts).replace("-( ", "-(")


def to_arxiv(query: str) -> str:
    """arXiv API search_query: all:term, all:"phrase", AND / OR / ANDNOT, parentheses."""
    if any(f in query for f in ("ti:", "abs:", "all:", "au:", "cat:")):
        return query  # already in arXiv syntax
    tokens = tokenize(query)
    parts: list[str] = []
    for idx, (kind, val) in enumerate(tokens):
        nxt = tokens[idx + 1][0] if idx + 1 < len(tokens) else None
        if kind == "TERM":
            val = val.rstrip("*")
            if val:
                parts.append("all:" + val)
        elif kind == "PHRASE":
            parts.append(f'all:"{val}"')
        elif kind == "AND":
            if nxt != "NOT":
                parts.append("AND")
        elif kind == "NOT":
            parts.append("ANDNOT")
        else:
            parts.append(val)
    return _join(parts)
