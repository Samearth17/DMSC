"""Boolean query parsing, formatting, and relevance evaluation.

Supports complex expressions with parentheses, OR disjunctions, AND conjunctions,
exclusions (-term), and multilingual phrase matching.
Example: ("Ooty" OR "ऊटी" OR "உட்டி") AND ("Indian Army" OR "भारतीय सेना") -filter:retweets
"""
import re


def is_boolean_query(text: str) -> bool:
    """Return True if text contains Boolean operators or grouping syntax."""
    if not text or not isinstance(text, str):
        return False
    # Check for AND, OR, parentheses, or negative term filters
    return bool(re.search(r'\b(AND|OR)\b|[()]|^\s*-\S+|\s+-\S+', text, flags=re.IGNORECASE))


def format_search_query(term: str) -> str:
    """Format a term or expression for engine search queries.

    Preserves Boolean expressions intact for search engines.
    Formats simple 'a or b or c' as '("a" OR "b" OR "c")'.
    Quotes simple phrases or terms.
    """
    cleaned = term.strip()
    if not cleaned:
        return '""'
    # If already a structured boolean query with parentheses or AND/OR
    if re.search(r'[()]|\bAND\b', cleaned, flags=re.IGNORECASE):
        return cleaned
    # If simple 'a or b or c' without parentheses
    if re.search(r'\bOR\b|\s+or\s+|\s*\|\s*', cleaned, flags=re.IGNORECASE):
        parts = [p.strip().strip('"\'') for p in re.split(r'\s+or\s+|\s*\|\s*', cleaned, flags=re.IGNORECASE) if p.strip()]
        if len(parts) > 1:
            return "(" + " OR ".join(f'"{p}"' for p in parts) + ")"
    # Simple term: escape quotes and wrap in quotes
    return '"' + cleaned.replace('"', ' ').replace('\\', ' ').strip() + '"'


def _match_phrase(phrase: str, text: str) -> bool:
    """Match phrase or word in text with boundary awareness."""
    clean_phrase = phrase.strip().strip('"\'').casefold()
    if not clean_phrase:
        return False
    # If phrase contains spaces or punctuation, substring search is appropriate
    if ' ' in clean_phrase or not clean_phrase.isalnum():
        return clean_phrase in text
    # Single word: use word boundary
    pattern = r"(?<!\w)" + re.escape(clean_phrase) + r"(?!\w)"
    return bool(re.search(pattern, text))


def eval_boolean_match(expression: str, text: str) -> bool:
    """Evaluate whether text satisfies expression.

    Supports:
    - Parenthesized OR groups: (A OR B OR C)
    - AND conjunctions: Group1 AND Group2
    - Negative exclusions: -term or -filter:something
    - Plain disjunctions: A or B or C
    """
    if not expression or not text:
        return False
    text_lower = text.casefold()

    raw = expression.strip()

    # Extract and evaluate negative filters: -word or -filter:retweets
    negatives = re.findall(r'(?:^|\s)-([^\s()]+)', raw)
    for neg in negatives:
        if neg.lower().startswith("filter:retweets"):
            # Check for common retweet markers or literal filter:retweets token
            if "rt @" in text_lower or text_lower.startswith("rt ") or "filter:retweets" in text_lower:
                return False
            continue
        neg_term = neg.strip('"\'').casefold()
        if neg_term and _match_phrase(neg_term, text_lower):
            return False

    # Strip out negative filter tokens from the positive expression
    pos_expr = re.sub(r'(?:^|\s)-[^\s()]+', '', raw).strip()
    if not pos_expr:
        return True

    # Split by top-level ' AND '
    # Handling parenthesized groups: replace AND outside parentheses
    and_parts = []
    current, depth = [], 0
    tokens = re.split(r'(\(|\)|\s+AND\s+|\s+and\s+)', pos_expr)
    for token in tokens:
        if not token:
            continue
        if token == '(':
            depth += 1
            current.append(token)
        elif token == ')':
            depth = max(0, depth - 1)
            current.append(token)
        elif re.match(r'^\s+and\s+$', token, flags=re.IGNORECASE) and depth == 0:
            part = "".join(current).strip()
            if part:
                and_parts.append(part)
            current = []
        else:
            current.append(token)
    if current:
        part = "".join(current).strip()
        if part:
            and_parts.append(part)

    if not and_parts:
        and_parts = [pos_expr]

    # Every AND part must evaluate to True
    for part in and_parts:
        part_clean = part.strip()
        # Remove surrounding outer parentheses if any
        if part_clean.startswith('(') and part_clean.endswith(')'):
            part_clean = part_clean[1:-1].strip()

        # Split by OR / or / |
        or_operands = [op.strip() for op in re.split(r'\s+or\s+|\s*\|\s*', part_clean, flags=re.IGNORECASE) if op.strip()]
        if not or_operands:
            continue

        # At least one OR operand must match
        part_matched = False
        for op in or_operands:
            clean_op = op.strip().strip('"\'')
            if _match_phrase(clean_op, text_lower):
                part_matched = True
                break
        if not part_matched:
            return False

    return True


def extract_matched_terms(expression: str, text: str) -> list[str]:
    """Return all terms/phrases from expression that appear in text."""
    if not expression or not text:
        return []
    text_lower = text.casefold()
    # Extract quoted phrases or single words (ignoring operators like AND, OR)
    candidates = re.findall(r'"([^"]+)"|\'([^\']+)\'|(\b[\w\u0900-\u0D7F]+\b)', expression)
    hits = []
    seen = set()
    for c1, c2, c3 in candidates:
        word = (c1 or c2 or c3).strip()
        if word.upper() in {"AND", "OR", "NOT"} or word.startswith("-"):
            continue
        if word.casefold() in seen:
            continue
        if _match_phrase(word, text_lower):
            hits.append(word)
            seen.add(word.casefold())
    return hits
