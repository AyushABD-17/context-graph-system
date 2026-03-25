const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000"

export async function fetchGraph(type = null, limit = 300, cluster = null) {
  try {
    const params = new URLSearchParams()
    if (type) params.append("type", type)
    params.append("limit", limit)
    if (cluster !== null) params.append("cluster", cluster)
    const res = await fetch(`${BASE}/graph?${params}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { nodes: [], edges: [] }
  }
}

export async function fetchNode(nodeId) {
  try {
    const res = await fetch(`${BASE}/node/${encodeURIComponent(nodeId)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { node: null, neighbors: [] }
  }
}

export async function fetchFlow(docId) {
  try {
    const res = await fetch(`${BASE}/flow/${encodeURIComponent(docId)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { flow: null }
  }
}

export async function sendQuery(message, history = [], sessionId = "default") {
  try {
    const res = await fetch(`${BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, session_id: sessionId })
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    return {
      answer: `Error: ${err.message} — is the backend running on port 8000?`,
      sql: null, data: [], row_count: 0
    }
  }
}

/**
 * Streaming query — returns an async generator of SSE events.
 * Each event is a parsed JSON object:
 *   {type: "sql",   sql: "..."}
 *   {type: "token", token: "..."}
 *   {type: "done",  highlighted_nodes: [...], highlighted_edges: [...], row_count: N, data: [...]}
 *   {type: "error", message: "..."}
 */
export async function* streamQuery(message, history = [], sessionId = "default") {
  const res = await fetch(`${BASE}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history, session_id: sessionId })
  })
  if (!res.ok) {
    yield { type: "error", message: `HTTP ${res.status}` }
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() // keep incomplete line in buffer

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6))
        } catch { /* skip malformed */ }
      }
    }
  }
}

/** Semantic / hybrid search over graph entities */
export async function searchEntities(q, topK = 50) {
  try {
    const res = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}&top_k=${topK}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { results: [], query: q, total: 0 }
  }
}

/** Load conversation history for a session */
export async function fetchHistory(sessionId) {
  try {
    const res = await fetch(`${BASE}/history/${encodeURIComponent(sessionId)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { turns: [] }
  }
}

/** Fetch graph analysis data */
export async function fetchAnalysis() {
  try {
    const [clustersRes, gapsRes, centralityRes] = await Promise.all([
      fetch(`${BASE}/analysis/clusters`),
      fetch(`${BASE}/analysis/gaps`),
      fetch(`${BASE}/analysis/centrality`),
    ])
    return {
      clusters: await clustersRes.json(),
      gaps: await gapsRes.json(),
      centrality: await centralityRes.json(),
    }
  } catch (err) {
    console.error(err)
    return { clusters: null, gaps: null, centrality: null }
  }
}

export async function fetchHealth() {
  try {
    const res = await fetch(`${BASE}/health`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (err) {
    console.error(err)
    return { status: "error" }
  }
}
