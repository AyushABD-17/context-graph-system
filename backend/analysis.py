"""
analysis.py — Graph clustering and advanced O2C flow analysis.

At startup: runs community detection + degree centrality on the graph.
Provides endpoints for cluster stats, top hub nodes, and flow gap detection.
"""

import json
from collections import defaultdict, Counter


def run_graph_analysis(graph_data: dict) -> dict:
    """
    Compute:
    1. Connected component IDs (fast community proxy without networkx dependency)
    2. Degree centrality per node
    3. Entity type distribution per community
    
    Modifies graph_data nodes in-place to add community_id and degree_centrality.
    Returns summary stats.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    node_map = {str(n["id"]): n for n in nodes}
    
    # --- Degree centrality ---
    degree = defaultdict(int)
    adj = defaultdict(set)
    for e in edges:
        src, tgt = str(e["source"]), str(e["target"])
        degree[src] += 1
        degree[tgt] += 1
        adj[src].add(tgt)
        adj[tgt].add(src)

    n = max(len(nodes) - 1, 1)
    for node in nodes:
        nid = str(node["id"])
        node["degree_centrality"] = round(degree[nid] / n, 6)
        node["degree"] = degree[nid]

    # --- Community detection via Union-Find (connected components as base clusters) ---
    parent = {str(n["id"]): str(n["id"]) for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[a] = b

    for e in edges:
        src, tgt = str(e["source"]), str(e["target"])
        if src in parent and tgt in parent:
            union(src, tgt)

    # Assign sequential community IDs
    root_to_community = {}
    cid_counter = [0]
    for node in nodes:
        nid = str(node["id"])
        root = find(nid)
        if root not in root_to_community:
            root_to_community[root] = cid_counter[0]
            cid_counter[0] += 1
        node["community_id"] = root_to_community[root]

    # --- Community stats ---
    community_stats = defaultdict(lambda: {"count": 0, "types": Counter()})
    for node in nodes:
        cid = node.get("community_id", 0)
        community_stats[cid]["count"] += 1
        community_stats[cid]["types"][node.get("type", "Unknown")] += 1

    stats = []
    for cid, data in sorted(community_stats.items(), key=lambda x: -x[1]["count"]):
        dominant_type = data["types"].most_common(1)[0][0] if data["types"] else "Unknown"
        stats.append({
            "community_id": cid,
            "node_count": data["count"],
            "dominant_type": dominant_type,
            "type_breakdown": dict(data["types"]),
        })

    # --- Top hub nodes by degree centrality ---
    top_hubs = sorted(nodes, key=lambda n: n.get("degree", 0), reverse=True)[:20]
    hub_list = [{"id": n["id"], "label": n.get("label"), "type": n.get("type"),
                 "degree": n.get("degree", 0), "community_id": n.get("community_id")}
                for n in top_hubs]

    return {"communities": stats, "top_hubs": hub_list, "community_count": len(stats)}


def detect_flow_gaps(graph_data: dict, conn) -> dict:
    """
    Run SQL queries to find O2C gaps:
    - Orders without delivery
    - Deliveries without invoice
    - Invoices without journal entry
    - Journal entries without payment
    """
    import sqlite3
    gaps = {}

    queries = {
        "orders_without_delivery": """
            SELECT COUNT(DISTINCT soh.sales_order) as count
            FROM sales_order_headers soh
            LEFT JOIN outbound_delivery_items odi ON soh.sales_order = odi.reference_sd_document
            WHERE odi.delivery_document IS NULL
        """,
        "deliveries_without_invoice": """
            SELECT COUNT(DISTINCT odh.delivery_document) as count
            FROM outbound_delivery_headers odh
            LEFT JOIN billing_document_items bdi ON odh.delivery_document = bdi.reference_sd_document
            WHERE bdi.billing_document IS NULL
        """,
        "invoices_without_journal": """
            SELECT COUNT(DISTINCT bdh.billing_document) as count
            FROM billing_document_headers bdh
            LEFT JOIN journal_entry_items_accounts_receivable j ON bdh.billing_document = j.reference_document
            WHERE j.accounting_document IS NULL
        """,
        "journal_without_payment": """
            SELECT COUNT(*) as count
            FROM journal_entry_items_accounts_receivable j
            LEFT JOIN payments_accounts_receivable p
              ON j.company_code = p.company_code
             AND j.accounting_document = p.clearing_accounting_document
            WHERE p.accounting_document IS NULL
        """,
    }

    cursor = conn.cursor()
    for key, sql in queries.items():
        try:
            cursor.execute(sql)
            row = cursor.fetchone()
            gaps[key] = row[0] if row else 0
        except Exception as e:
            gaps[key] = f"error: {e}"

    return gaps
