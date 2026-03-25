from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sqlite3
import json
import os
from query_engine import process, build_node_property_index, generate_sql, execute_sql, generate_answer, extract_node_ids_with_index, find_connecting_edges, call_llm
from semantic_search import build_entity_corpus, hybrid_search
from memory import init_memory_db, save_turn, load_history, list_sessions
from analysis import run_graph_analysis, detect_flow_gaps
import uvicorn

app = FastAPI(title="SAP Graph System", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup: load graph + build indices ──────────────────────────────────────
with open("graph.json", "r", encoding="utf-8") as f:
    graph_data = json.load(f)

print(f"[startup] Running graph analysis on {len(graph_data.get('nodes', []))} nodes...")
analysis_summary = run_graph_analysis(graph_data)   # adds community_id + degree_centrality to nodes in-place
print(f"[startup] Communities: {analysis_summary['community_count']}, Top hub: {analysis_summary['top_hubs'][0]['label'] if analysis_summary['top_hubs'] else 'N/A'}")

print(f"[startup] Building property index...")
node_property_index = build_node_property_index(graph_data)
print(f"[startup] Index: {len(node_property_index)} entries")

print(f"[startup] Building semantic search corpus...")
entity_corpus = build_entity_corpus(graph_data)
print(f"[startup] Corpus: {entity_corpus['n_docs']} documents")

print(f"[startup] Initialising memory DB...")
init_memory_db()
print(f"[startup] Ready.")


# ── Models ────────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    message: str
    history: list = []        # [{role, text}]
    session_id: str = "default"


# ── Standard query endpoint ───────────────────────────────────────────────────
@app.post("/query")
def query_endpoint(req: QueryRequest):
    conn = sqlite3.connect("graph.db")
    
    # Persist user turn
    save_turn(req.session_id, "user", req.message)
    
    result = process(req.message, conn, graph_data, node_property_index, req.history)
    conn.close()
    
    # Persist bot turn
    save_turn(
        req.session_id, "bot", result.get("answer", ""),
        sql_query=result.get("sql"),
        row_count=result.get("row_count", 0),
        highlighted_node_count=len(result.get("highlighted_nodes", [])),
    )
    return result


# ── Streaming query endpoint ──────────────────────────────────────────────────
@app.post("/query/stream")
def query_stream(req: QueryRequest):
    """
    SSE streaming endpoint.
    First event: {"type":"sql", "sql":"..."}
    Middle events: {"type":"token", "token":"..."}
    Final event:  {"type":"done", "highlighted_nodes":[...], "highlighted_edges":[...], "row_count": N}
    """
    def event_generator():
        try:
            conn = sqlite3.connect("graph.db")

            # Save user turn
            save_turn(req.session_id, "user", req.message)

            # Step 1: Generate + execute SQL (fast, synchronous)
            from query_engine import is_on_topic
            if not is_on_topic(req.message, req.history):
                yield f'data: {json.dumps({"type":"token","token":"This system answers SAP Order-to-Cash questions only."})}\n\n'
                yield f'data: {json.dumps({"type":"done","highlighted_nodes":[],"highlighted_edges":[],"row_count":0})}\n\n'
                conn.close()
                return

            sql = generate_sql(req.message, req.history)
            yield f'data: {json.dumps({"type":"sql","sql":sql})}\n\n'

            data = execute_sql(sql, conn)
            row_count = len(data)
            conn.close()

            # Step 2: Determine highlighted nodes
            highlighted_nodes = []
            highlighted_edges = []
            if data and node_property_index:
                highlighted_nodes = extract_node_ids_with_index(data, node_property_index)
                if highlighted_nodes:
                    highlighted_edges = find_connecting_edges(highlighted_nodes, graph_data)

            # Step 3: Build LLM answer prompt
            history_text = ""
            if req.history:
                for turn in req.history[-4:]:
                    role = "User" if turn.get("role") == "user" else "Assistant"
                    history_text += f"{role}: {turn.get('text','')}\n"

            prompt = f"""You are a SAP business analyst answering questions about Order-to-Cash data.

{f'CONVERSATION HISTORY:{chr(10)}{history_text}' if history_text else ''}
Question: {req.message}
SQL executed: {sql}
Total rows returned: {row_count}
Data sample (up to 30 rows): {json.dumps(data[:30], indent=2)}

Rules:
- Answer in 2-5 sentences using ONLY the data above
- Always mention the exact count of records found
- Reference specific values from the data
- Do NOT make up any facts not present in the data"""

            # Step 4: Stream LLM tokens
            from groq import Groq
            groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
            full_answer = []

            stream = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                stream=True,
            )

            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    full_answer.append(token)
                    yield f'data: {json.dumps({"type":"token","token":token})}\n\n'

            # Final event with graph highlighting data
            yield f'data: {json.dumps({"type":"done","highlighted_nodes":highlighted_nodes,"highlighted_edges":highlighted_edges,"row_count":row_count,"data":data[:100]})}\n\n'

            # Persist bot turn
            save_turn(req.session_id, "bot", "".join(full_answer),
                      sql_query=sql, row_count=row_count,
                      highlighted_node_count=len(highlighted_nodes))

        except Exception as e:
            yield f'data: {json.dumps({"type":"error","message":str(e)})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ── Semantic search endpoint ──────────────────────────────────────────────────
@app.get("/search")
def search_entities(q: str = Query(..., description="Natural language search query"), top_k: int = 50):
    """Hybrid TF-IDF + keyword search over all graph node properties."""
    if not q.strip():
        return {"results": [], "query": q}
    results = hybrid_search(q, entity_corpus, top_k=top_k)
    return {"results": results, "query": q, "total": len(results)}


# ── Memory / history endpoints ────────────────────────────────────────────────
@app.get("/history/{session_id}")
def get_history(session_id: str, limit: int = 50):
    """Load conversation history for a session."""
    turns = load_history(session_id, limit=limit)
    return {"session_id": session_id, "turns": turns, "count": len(turns)}


@app.get("/sessions")
def get_sessions():
    """List recent conversation sessions."""
    return {"sessions": list_sessions(limit=20)}


# ── Analysis endpoints ────────────────────────────────────────────────────────
@app.get("/analysis/clusters")
def get_clusters():
    """Return community detection results and top hub nodes."""
    return {
        "communities": analysis_summary["communities"][:20],  # top 20 communities
        "community_count": analysis_summary["community_count"],
        "top_hubs": analysis_summary["top_hubs"],
    }


@app.get("/analysis/gaps")
def get_flow_gaps():
    """Detect O2C flow gaps (missing links between document types)."""
    conn = sqlite3.connect("graph.db")
    gaps = detect_flow_gaps(graph_data, conn)
    conn.close()
    return {"gaps": gaps}


@app.get("/analysis/centrality")
def get_centrality():
    """Return the top 30 nodes by degree centrality."""
    nodes = graph_data.get("nodes", [])
    top = sorted(nodes, key=lambda n: n.get("degree_centrality", 0), reverse=True)[:30]
    return {"nodes": [{"id": n["id"], "label": n.get("label"), "type": n.get("type"),
                        "degree_centrality": n.get("degree_centrality", 0),
                        "degree": n.get("degree", 0)} for n in top]}


# ── Health + existing endpoints ───────────────────────────────────────────────
@app.get("/health")
def health_endpoint():
    return {
        "status": "ok",
        "node_count": len(graph_data.get("nodes", [])),
        "edge_count": len(graph_data.get("edges", [])),
        "community_count": analysis_summary["community_count"],
        "index_entries": len(node_property_index),
        "corpus_docs": entity_corpus["n_docs"],
    }


@app.get("/graph")
def fetch_graph(type: str = None, limit: int = 1500, connected_only: bool = True,
                cluster: int = None):
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if type:
        nodes = [n for n in nodes if n.get("type") == type]
    if cluster is not None:
        nodes = [n for n in nodes if n.get("community_id") == cluster]

    node_ids = {str(n["id"]) for n in nodes}
    edges = [e for e in edges if str(e["source"]) in node_ids and str(e["target"]) in node_ids]

    if connected_only:
        connected_ids = set()
        for e in edges:
            connected_ids.add(str(e["source"]))
            connected_ids.add(str(e["target"]))
        nodes = [n for n in nodes if str(n["id"]) in connected_ids]

    nodes = nodes[:limit]
    limited_ids = {str(n["id"]) for n in nodes}
    edges = [e for e in edges if str(e["source"]) in limited_ids and str(e["target"]) in limited_ids]
    edges = edges[:limit * 3]

    return {"nodes": nodes, "edges": edges}


@app.get("/node/{node_id}")
def fetch_node(node_id: str):
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    node = next((n for n in nodes if str(n["id"]) == node_id), None)
    if not node:
        return {"error": "Not found"}

    neighbors = []
    for e in edges:
        if str(e["source"]) == node_id:
            tgt = next((n for n in nodes if str(n["id"]) == str(e["target"])), None)
            if tgt:
                neighbors.append({"id": tgt["id"], "label": tgt.get("label"), "relation": e.get("relation"), "type": tgt.get("type")})
        elif str(e["target"]) == node_id:
            src = next((n for n in nodes if str(n["id"]) == str(e["source"])), None)
            if src:
                neighbors.append({"id": src["id"], "label": src.get("label"), "relation": e.get("relation"), "type": src.get("type")})

    return {"node": node, "neighbors": neighbors}


@app.get("/flow/{doc_id}")
def fetch_flow(doc_id: str):
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    start_node = next((n for n in nodes if doc_id in str(n["id"])), None)
    if not start_node:
        return {"error": f"Document {doc_id} not found in graph"}

    visited_nodes = {str(start_node["id"])}
    flow_edges = []
    queue = [str(start_node["id"])]

    while queue:
        curr = queue.pop(0)
        for e in edges:
            src, tgt = str(e["source"]), str(e["target"])
            if src == curr and tgt not in visited_nodes:
                visited_nodes.add(tgt)
                queue.append(tgt)
                flow_edges.append(e)
            elif tgt == curr and src not in visited_nodes:
                visited_nodes.add(src)
                queue.append(src)
                flow_edges.append(e)

    return {"nodes": [n for n in nodes if str(n["id"]) in visited_nodes], "edges": flow_edges}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
