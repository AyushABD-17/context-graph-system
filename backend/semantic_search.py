"""
semantic_search.py — Hybrid entity search over SAP graph nodes.

Algorithm: TF-IDF-style term scoring + substring matching over node property values.
No external vector DB required — fully offline, runs at startup.
"""

import re
import math
from collections import defaultdict


def build_entity_corpus(graph_data: dict) -> dict:
    """
    Build a searchable corpus from all node property values.
    Returns:
        corpus: {node_id -> {"text": str, "node": dict, "terms": set}}
        idf:    {term -> inverse document frequency}
    """
    docs = {}
    term_doc_count = defaultdict(int)  # term -> num docs containing it

    for node in graph_data.get("nodes", []):
        nid = str(node["id"])
        # Concatenate all property values into a single searchable text
        parts = []
        for k, v in node.items():
            if v is not None and str(v).strip():
                parts.append(str(v).strip().lower())
        text = " ".join(parts)
        terms = set(re.findall(r'\w+', text))

        docs[nid] = {
            "text": text,
            "terms": terms,
            "node": node,
            "type": node.get("type", ""),
            "label": node.get("label", nid),
        }
        for t in terms:
            term_doc_count[t] += 1

    n_docs = max(len(docs), 1)
    idf = {term: math.log(n_docs / (count + 1)) + 1
           for term, count in term_doc_count.items()}

    return {"docs": docs, "idf": idf, "n_docs": n_docs}


def hybrid_search(query: str, corpus: dict, top_k: int = 50) -> list:
    """
    Score nodes by:
      1. TF-IDF term overlap between query and node text
      2. Bonus for exact substring match in any property value
      3. Bonus for entity type match (e.g. 'customer' in query → Customer nodes)

    Returns: list of {id, label, type, score} sorted descending by score
    """
    if not query or not corpus:
        return []

    docs = corpus.get("docs", {})
    idf = corpus.get("idf", {})

    query_lower = query.lower().strip()
    query_terms = re.findall(r'\w+', query_lower)

    # Entity type keywords → node types
    TYPE_HINTS = {
        "customer": "Customer",
        "order": "SalesOrder",
        "delivery": "Delivery",
        "invoice": "Invoice",
        "payment": "Payment",
        "journal": "JournalEntry",
        "product": "Product",
        "plant": "Plant",
        "material": "Product",
        "billing": "Invoice",
    }
    preferred_types = set()
    for kw, t in TYPE_HINTS.items():
        if kw in query_lower:
            preferred_types.add(t)

    scores = {}
    for nid, doc in docs.items():
        score = 0.0

        # 1. TF-IDF term overlap
        doc_terms = doc["terms"]
        doc_text = doc["text"]
        doc_len = max(len(doc_text.split()), 1)

        for term in query_terms:
            if term in doc_terms:
                tf = doc_text.count(term) / doc_len
                idf_val = idf.get(term, 1.0)
                score += tf * idf_val

        if score == 0.0:
            continue  # skip nodes with no term overlap at all

        # 2. Bonus: exact substring match in the full text
        if query_lower in doc_text:
            score += 3.0

        # Check individual query terms as substrings
        for term in query_terms:
            if len(term) >= 3 and term in doc_text:
                score += 0.5

        # 3. Bonus: node type matches query intent
        if doc["type"] in preferred_types:
            score += 1.5

        scores[nid] = score

    # Sort and return top_k
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for nid, score in ranked:
        doc = docs[nid]
        results.append({
            "id": nid,
            "label": doc["label"],
            "type": doc["type"],
            "score": round(score, 4),
        })

    return results
