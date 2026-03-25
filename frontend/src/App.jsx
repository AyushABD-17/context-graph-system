import React, { useState, useEffect, useRef, useCallback } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { fetchGraph, sendQuery, streamQuery, fetchNode, searchEntities, fetchHistory, fetchAnalysis } from "./api"

function useContainerSize(ref) {
  const [size, setSize] = useState({ width: 800, height: 600 })
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setSize({ width: Math.floor(width), height: Math.floor(height) })
      }
    })
    ro.observe(ref.current)
    // Initial measurement
    const { width, height } = ref.current.getBoundingClientRect()
    setSize({ width: Math.floor(width), height: Math.floor(height) })
    return () => ro.disconnect()
  }, [ref])
  return size
}

// Semantic colors per O2C entity type
const TYPE_COLORS = {
  Customer:      "#a78bfa",
  SalesOrder:    "#60a5fa",
  SalesOrderItem:"#93c5fd",
  ScheduleLine:  "#bfdbfe",
  Delivery:      "#34d399",
  DeliveryItem:  "#6ee7b7",
  Invoice:       "#2dd4bf",
  InvoiceItem:   "#99f6e4",
  Cancellation:  "#f87171",
  JournalEntry:  "#818cf8",
  Payment:       "#10b981",
  Product:       "#fbbf24",
  Plant:         "#fb923c",
  Address:       "#d1d5db",
  default:       "#e5e7eb",
}

// Community cluster color palette (20 distinct colors)
const CLUSTER_PALETTE = [
  "#6366f1","#f59e0b","#10b981","#ef4444","#3b82f6",
  "#8b5cf6","#ec4899","#14b8a6","#f97316","#84cc16",
  "#06b6d4","#a855f7","#eab308","#22c55e","#f43f5e",
  "#0ea5e9","#d946ef","#4ade80","#fb923c","#818cf8",
]

function getNodeColor(node, selectedId, highlightSet, colorByCluster = false) {
  if (node.id === selectedId) return "#1d4ed8"
  if (highlightSet && highlightSet.size > 0 && highlightSet.has(node.id)) {
    return "#f59e0b"
  }
  if (colorByCluster && node.community_id !== undefined) {
    return CLUSTER_PALETTE[node.community_id % CLUSTER_PALETTE.length]
  }
  return TYPE_COLORS[node.type] || TYPE_COLORS.default
}

// Generate or retrieve a stable session ID from localStorage
function getSessionId() {
  let sid = localStorage.getItem("sap_graph_session")
  if (!sid) {
    sid = "sess_" + Math.random().toString(36).slice(2, 11)
    localStorage.setItem("sap_graph_session", sid)
  }
  return sid
}
const SESSION_ID = getSessionId()

export default function App() {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [messages, setMessages] = useState([
    { role: "bot", text: "Hi! I can help you analyze the Order to Cash process. Your conversation is saved across sessions." }
  ])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [selectedNode, setSelectedNode] = useState(null)
  const [selectedDetails, setSelectedDetails] = useState(null)
  const [tooltipPos, setTooltipPos] = useState({ x: 20, y: 60 })
  const [expandMode, setExpandMode] = useState(false)
  // Graph display modes
  const [colorByCluster, setColorByCluster] = useState(false)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [analysisData, setAnalysisData] = useState(null)
  // Semantic search
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const searchTimerRef = useRef(null)
  // Query highlighting state — dual: state for React UI, refs for canvas paintNode
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightEdgeKeys, setHighlightEdgeKeys] = useState(new Set())
  const [highlightLabel, setHighlightLabel] = useState("")
  const highlightNodesRef = useRef(new Set())
  const highlightEdgesRef = useRef(new Set())
  const selectedNodeRef = useRef(null)
  const colorByClusterRef = useRef(false)
  const messagesEndRef = useRef(null)
  const graphRef = useRef(null)
  const paneRef = useRef(null)
  const { width: graphWidth, height: graphHeight } = useContainerSize(paneRef)

  useEffect(() => {
    loadGraph()
    loadSessionHistory()
  }, [])

  // Load prior conversation from memory
  async function loadSessionHistory() {
    try {
      const hist = await fetchHistory(SESSION_ID)
      if (hist.turns && hist.turns.length > 0) {
        const restored = hist.turns.map(t => ({
          role: t.role,
          text: t.text,
          sql: t.sql || null,
          row_count: t.row_count || 0,
          data: [],
        }))
        setMessages(m => [
          { role: "bot", text: "Hi! I can help you analyze the Order to Cash process. Your conversation is saved across sessions." },
          { role: "bot", text: `↺ Restored ${hist.turns.length} messages from your previous session.` },
          ...restored
        ])
      }
    } catch (e) { /* silently ignore */ }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Force canvas repaint + zoom to highlighted nodes when highlights change
  useEffect(() => {
    const fg = graphRef.current
    if (!fg) return
    try {
      if (typeof fg.refresh === "function") fg.refresh()
      else if (typeof fg.pauseAnimation === "function") {
        fg.pauseAnimation()
        requestAnimationFrame(() => fg.resumeAnimation?.())
      }
      // Zoom to fit highlighted nodes after a brief delay
      if (highlightNodes.size > 0) {
        setTimeout(() => {
          fg.zoomToFit?.(600, 80, node => highlightNodes.has(node.id))
        }, 300)
      }
    } catch (e) {}
  }, [highlightNodes])

  async function loadGraph() {
    const data = await fetchGraph(null, 1500)
    const nodes = (data.nodes || []).map(n => ({
      id: String(n.id),
      label: n.label || String(n.id),
      type: n.type || "",
      ...n
    }))
    // Build an index for quick "does node exist" lookup
    const nodeIds = new Set(nodes.map(n => n.id))
    const links = (data.edges || [])
      .filter(e => nodeIds.has(String(e.source)) && nodeIds.has(String(e.target)))
      .map((e, i) => ({
        id: `e${i}`,
        source: String(e.source),
        target: String(e.target),
        relation: e.relation || ""
      }))
    setGraphData({ nodes, links })
    setSelectedNode(null)
    selectedNodeRef.current = null
    setSelectedDetails(null)
    setHighlightNodes(new Set())
    setHighlightEdgeKeys(new Set())
    highlightNodesRef.current = new Set()
    highlightEdgesRef.current = new Set()
    setHighlightLabel("")
    // Tune d3 forces after data is set — stronger repulsion creates proper hub-spoke layout
    setTimeout(() => {
      if (graphRef.current) {
        graphRef.current.d3Force("charge")?.strength(-180)
        graphRef.current.d3Force("link")?.distance(60).strength(1)
        graphRef.current.d3ReheatSimulation()
      }
    }, 50)
  }

  async function handleNodeClick(node, event) {
    setSelectedNode(node.id)
    selectedNodeRef.current = node.id
    // Position tooltip near click — keep inside the graph pane
    const rect = event.target?.getBoundingClientRect?.() || { left: 0, top: 0 }
    const px = Math.min(event.clientX - rect.left + 12, (rect.width || 800) - 340)
    const py = Math.min(event.clientY - rect.top + 12, (rect.height || 600) - 480)
    setTooltipPos({ x: Math.max(px, 8), y: Math.max(py, 60) })
    try {
      const detail = await fetchNode(node.id)
      setSelectedDetails(detail)
    } catch (e) {
      console.error(e)
    }
  }

  // Expand node: highlight it + all its direct neighbors in the graph
  function expandNeighborhood(nodeId, neighbors) {
    const neighborIds = (neighbors || []).map(n => String(n.id))
    const allIds = new Set([nodeId, ...neighborIds])
    // Build edge keys for edges touching this node
    const edgeKeys = new Set()
    ;(graphData.links || []).forEach(link => {
      const src = link.source?.id ?? link.source
      const tgt = link.target?.id ?? link.target
      if (String(src) === nodeId || String(tgt) === nodeId) {
        edgeKeys.add(`${src}|${tgt}`)
        edgeKeys.add(`${tgt}|${src}`)
      }
    })
    highlightNodesRef.current = allIds
    highlightEdgesRef.current = edgeKeys
    setHighlightNodes(allIds)
    setHighlightEdgeKeys(edgeKeys)
    setHighlightLabel(`Neighborhood: ${neighborIds.length} connections`)
    setExpandMode(true)
    // Zoom to fit the neighborhood
    setTimeout(() => {
      graphRef.current?.zoomToFit?.(600, 60, n => allIds.has(n.id))
    }, 300)
  }

  function resetView() {
    highlightNodesRef.current = new Set()
    highlightEdgesRef.current = new Set()
    setHighlightNodes(new Set())
    setHighlightEdgeKeys(new Set())
    setHighlightLabel("")
    setExpandMode(false)
    setSelectedNode(null)
    setSelectedDetails(null)
    selectedNodeRef.current = null
    setTimeout(() => graphRef.current?.zoomToFit?.(600, 40), 200)
  }

  // Navigate to a neighboring node (click from tooltip)
  async function navigateToNode(nodeId) {
    const node = graphData.nodes.find(n => n.id === nodeId)
    if (!node) return
    setSelectedNode(nodeId)
    selectedNodeRef.current = nodeId
    try {
      const detail = await fetchNode(nodeId)
      setSelectedDetails(detail)
      // Center graph on this node
      if (graphRef.current && node.x != null) {
        graphRef.current.centerAt(node.x, node.y, 600)
        graphRef.current.zoom(2.5, 600)
      }
    } catch (e) { console.error(e) }
  }

  function handlePaneClick() {
    setSelectedNode(null)
    setSelectedDetails(null)
    // Don't clear highlights on background click — user may want to inspect
  }

  // Debounced semantic search: highlights matching nodes in graph
  function handleSearchInput(val) {
    setSearchQuery(val)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!val.trim()) {
      setSearchResults([])
      // Clear search highlights
      highlightNodesRef.current = new Set()
      highlightEdgesRef.current = new Set()
      setHighlightNodes(new Set())
      setHighlightEdgeKeys(new Set())
      setHighlightLabel("")
      return
    }
    searchTimerRef.current = setTimeout(async () => {
      setSearchLoading(true)
      try {
        const res = await searchEntities(val, 80)
        setSearchResults(res.results || [])
        if (res.results && res.results.length > 0) {
          const nodeSet = new Set(res.results.map(r => String(r.id)))
          highlightNodesRef.current = nodeSet
          highlightEdgesRef.current = new Set()
          setHighlightNodes(nodeSet)
          setHighlightEdgeKeys(new Set())
          setHighlightLabel(`Search: ${res.total} entities matched`)
          // Trigger canvas repaint
          const fg = graphRef.current
          if (fg) { try { fg.refresh?.() } catch {} }
        }
      } finally {
        setSearchLoading(false)
      }
    }, 300)
  }

  function handleClusterToggle() {
    const next = !colorByCluster
    colorByClusterRef.current = next
    setColorByCluster(next)
    const fg = graphRef.current
    if (fg) { try { fg.refresh?.() } catch {} }
  }

  async function handleAnalysisToggle() {
    const next = !showAnalysis
    setShowAnalysis(next)
    if (next && !analysisData) {
      const data = await fetchAnalysis()
      setAnalysisData(data)
    }
  }

  // Streaming handleSend — tokens appear progressively in the chat bubble
  async function handleSend() {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput("")
    const userMsg = { role: "user", text: question }
    setMessages(m => [...m, userMsg])
    setLoading(true)
    // Reset previous highlights
    highlightNodesRef.current = new Set()
    highlightEdgesRef.current = new Set()
    setHighlightNodes(new Set())
    setHighlightEdgeKeys(new Set())
    setHighlightLabel("")
    // Clear search results when sending a query
    setSearchQuery("")
    setSearchResults([])

    // Add a placeholder bot message that we'll stream into
    const botMsgId = Date.now()
    setMessages(m => [...m, { role: "bot", text: "", sql: null, data: [], row_count: 0, streaming: true, id: botMsgId }])

    try {
      const currentHistory = messages.concat(userMsg).map(m => ({ role: m.role, text: m.text }))

      for await (const event of streamQuery(question, currentHistory, SESSION_ID)) {
        if (event.type === "sql") {
          setMessages(m => m.map(msg =>
            msg.id === botMsgId ? { ...msg, sql: event.sql } : msg
          ))
        } else if (event.type === "token") {
          setMessages(m => m.map(msg =>
            msg.id === botMsgId ? { ...msg, text: msg.text + event.token } : msg
          ))
        } else if (event.type === "done") {
          // Finalize message + apply graph highlighting
          setMessages(m => m.map(msg =>
            msg.id === botMsgId
              ? { ...msg, streaming: false, data: event.data || [], row_count: event.row_count || 0 }
              : msg
          ))
          if (event.highlighted_nodes && event.highlighted_nodes.length > 0) {
            const nodeSet = new Set(event.highlighted_nodes.map(String))
            const edgeSet = new Set((event.highlighted_edges || []).map(e => `${e.source}|${e.target}`))
            highlightNodesRef.current = nodeSet
            highlightEdgesRef.current = edgeSet
            setHighlightNodes(nodeSet)
            setHighlightEdgeKeys(edgeSet)
            setHighlightLabel(`${nodeSet.size} node${nodeSet.size !== 1 ? 's' : ''} matched`)
          }
        } else if (event.type === "error") {
          setMessages(m => m.map(msg =>
            msg.id === botMsgId ? { ...msg, text: "Error: " + event.message, streaming: false } : msg
          ))
        }
      }
    } catch (e) {
      setMessages(m => m.map(msg =>
        msg.id === botMsgId ? { ...msg, text: "Request failed: " + e.message, streaming: false } : msg
      ))
    } finally {
      setLoading(false)
    }
  }

  // paintNode reads from refs — always fresh, no useCallback closure issues
  const paintNode = useCallback((node, ctx, globalScale) => {
    const hlNodes = highlightNodesRef.current
    const selId   = selectedNodeRef.current
    const cbc     = colorByClusterRef.current
    const isSelected   = node.id === selId
    const isHighlighted = hlNodes.size > 0 && hlNodes.has(node.id)
    const isDimmed      = hlNodes.size > 0 && !isHighlighted && !isSelected
    const color = getNodeColor(node, selId, hlNodes, cbc)
    // Scale radius by degree centrality for hub visibility
    const baseR = isSelected ? 10 : isHighlighted ? 10 : Math.min(5 + (node.degree || 0) * 0.05, 9)
    const r = baseR

    ctx.globalAlpha = isDimmed ? 0.15 : 1.0

    // Amber glow rings for highlighted nodes
    if (isHighlighted && !isSelected) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 7, 0, 2 * Math.PI)
      ctx.fillStyle = "rgba(245,158,11,0.12)"
      ctx.fill()
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI)
      ctx.fillStyle = "rgba(245,158,11,0.35)"
      ctx.fill()
    }
    // Blue glow for selected
    if (isSelected) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI)
      ctx.fillStyle = "rgba(29,78,216,0.2)"
      ctx.fill()
    }
    // Main circle
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    // Border
    ctx.lineWidth = (isSelected || isHighlighted) ? 1.5 : 0.6
    ctx.strokeStyle = isSelected ? "#1d4ed8" : isHighlighted ? "#d97706" : "rgba(255,255,255,0.5)"
    ctx.stroke()
    // Label
    if (isHighlighted || isSelected || globalScale > 1.8) {
      const label = String(node.label || node.id).slice(0, 20)
      const fontSize = Math.max((isHighlighted ? 11 : 8) / globalScale, 2.5)
      ctx.globalAlpha = isDimmed ? 0.15 : 1.0
      ctx.font = `${isHighlighted || isSelected ? 'bold ' : ''}${fontSize}px Inter, sans-serif`
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillStyle = isSelected ? "#1d4ed8" : isHighlighted ? "#92400e" : "#374151"
      ctx.fillText(label, node.x, node.y + r + fontSize * 0.9)
    }
    ctx.globalAlpha = 1.0
  }, []) // stable — reads from refs, not closures

  const selectedDetailsNode = selectedDetails?.node
  const neighbors = selectedDetails?.neighbors || []

  return (
    <div className="app">
      <div className="top-nav">
        <div className="nav-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 6h16M4 12h16M4 18h16"></path>
          </svg>
        </div>
        <div className="nav-breadcrumbs">
          Mapping / <strong>Order to Cash</strong>
        </div>
      </div>

      <div className="main-content">
        <div ref={paneRef} className="graph-pane" style={{ position: "relative" }}>

          {/* Overlay buttons */}
          <div className="graph-overlay-btns">
            <button className="floating-btn" onClick={loadGraph}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/>
              </svg>
              Fit Graph
            </button>
            {(highlightNodes.size > 0 || selectedNode) && (
              <button className="floating-btn" onClick={resetView} style={{ background: "#fef3c7", borderColor: "#fde68a", color: "#92400e" }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
                </svg>
                Reset View
              </button>
            )}
            <button
              className="floating-btn dark"
              onClick={handleClusterToggle}
              style={colorByCluster ? { background: "#ede9fe", borderColor: "#c4b5fd", color: "#5b21b6" } : {}}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="7" cy="8" r="3"/><circle cx="17" cy="8" r="3"/><circle cx="12" cy="18" r="3"/>
                <line x1="9.5" y1="9.5" x2="14.5" y2="9.5"/><line x1="9" y1="10" x2="13" y2="16"/><line x1="15" y1="10" x2="13" y2="15"/>
              </svg>
              {colorByCluster ? "Type Colors" : "Cluster Colors"}
            </button>
            <button
              className="floating-btn dark"
              onClick={handleAnalysisToggle}
              style={showAnalysis ? { background: "#f0fdf4", borderColor: "#86efac", color: "#15803d" } : {}}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/>
              </svg>
              {showAnalysis ? "Hide Analysis" : "Analysis"}
            </button>
            <button className="floating-btn dark" onClick={() => graphRef.current?.zoomToFit?.(400, 40)}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
              </svg>
              Zoom Fit
            </button>
          </div>

          {/* Semantic Search Bar */}
          <div style={{ position: "absolute", top: 52, left: 12, right: 12, zIndex: 15, maxWidth: 420 }}>
            <div style={{ position: "relative" }}>
              <input
                type="text"
                value={searchQuery}
                onChange={e => handleSearchInput(e.target.value)}
                placeholder="🔍 Search entities… (customer, plant, order ID, product name)"
                style={{
                  width: "100%", padding: "8px 38px 8px 14px", fontSize: 12,
                  borderRadius: 20, border: "1.5px solid",
                  borderColor: searchQuery ? "#93c5fd" : "rgba(0,0,0,0.1)",
                  background: "rgba(255,255,255,0.95)", boxShadow: searchQuery ? "0 2px 12px rgba(59,130,246,0.15)" : "0 1px 4px rgba(0,0,0,0.08)",
                  outline: "none", boxSizing: "border-box",
                  transition: "border-color 0.2s, box-shadow 0.2s"
                }}
              />
              {searchLoading && (
                <span style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", fontSize: 10, color: "#9ca3af" }}>...</span>
              )}
              {searchQuery && !searchLoading && searchResults.length > 0 && (
                <span style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)",
                  fontSize: 10, fontWeight: 700, color: "#3b82f6", background: "#eff6ff", borderRadius: 10, padding: "1px 7px" }}>
                  {searchResults.length}
                </span>
              )}
            </div>
          </div>

          {/* Analysis Panel */}
          {showAnalysis && analysisData && (
            <div style={{
              position: "absolute", top: 100, right: 12, width: 280, zIndex: 20,
              background: "rgba(255,255,255,0.97)", borderRadius: 12, boxShadow: "0 4px 24px rgba(0,0,0,0.12)",
              border: "1px solid #e5e7eb", padding: 16, maxHeight: "60vh", overflowY: "auto"
            }}>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 12, color: "#111827" }}>📊 Graph Analysis</div>

              {/* Flow Gaps */}
              {analysisData.gaps?.gaps && (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>O2C Flow Gaps</div>
                  {Object.entries(analysisData.gaps.gaps).map(([key, val]) => (
                    <div key={key} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px solid #f1f5f9" }}>
                      <span style={{ fontSize: 11, color: "#374151" }}>{key.replace(/_/g, " ")}</span>
                      <span style={{ fontSize: 11, fontWeight: 700, color: typeof val === "number" && val > 0 ? "#ef4444" : "#10b981" }}>{val}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Top Hub Nodes */}
              {analysisData.clusters?.top_hubs && (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Top Hub Nodes</div>
                  {analysisData.clusters.top_hubs.slice(0, 8).map((h, i) => (
                    <div key={i} onClick={() => navigateToNode(String(h.id))}
                      style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 6px", borderRadius: 6,
                        cursor: "pointer", marginBottom: 2, transition: "background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background = "#f9fafb"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: CLUSTER_PALETTE[h.community_id % 20] || "#e5e7eb", display: "inline-block", flexShrink: 0 }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#111827", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.label}</div>
                        <div style={{ fontSize: 10, color: "#9ca3af" }}>{h.type} · {h.degree} connections</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Community Breakdown */}
              {analysisData.clusters?.communities && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                    {analysisData.clusters.community_count} Communities
                  </div>
                  {analysisData.clusters.communities.slice(0, 6).map((c, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", borderBottom: "1px solid #f1f5f9" }}>
                      <span style={{ width: 10, height: 10, borderRadius: 2, background: CLUSTER_PALETTE[c.community_id % 20] || "#e5e7eb", display: "inline-block", flexShrink: 0 }} />
                      <div style={{ flex: 1 }}>
                        <span style={{ fontSize: 11, color: "#374151" }}>{c.dominant_type}</span>
                        <span style={{ fontSize: 10, color: "#9ca3af", marginLeft: 6 }}>{c.node_count} nodes</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Query Highlight Legend */}
          {highlightLabel && (
            <div style={{
              position: "absolute", top: 16, left: "50%", transform: "translateX(-50%)",
              background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 20,
              padding: "4px 14px", fontSize: 12, fontWeight: 600, color: "#92400e",
              display: "flex", alignItems: "center", gap: 6, zIndex: 15,
              boxShadow: "0 2px 8px rgba(245,158,11,0.2)"
            }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b", display: "inline-block" }} />
              Query highlighted: {highlightLabel}
              <button onClick={() => { setHighlightNodes(new Set()); setHighlightEdgeKeys(new Set()); setHighlightLabel("") }}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#d97706", fontSize: 14, lineHeight: 1, padding: 0, marginLeft: 4 }}>✕</button>
            </div>
          )}

          {/* Force Graph */}
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => "replace"}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.fillStyle = color
              ctx.beginPath()
              ctx.arc(node.x, node.y, 9, 0, 2 * Math.PI, false)
              ctx.fill()
            }}
            linkColor={(link) => {
              if (highlightEdgeKeys.size === 0) return "rgba(147,197,253,0.55)"
              const key = `${link.source?.id ?? link.source}|${link.target?.id ?? link.target}`
              const keyRev = `${link.target?.id ?? link.target}|${link.source?.id ?? link.source}`
              return (highlightEdgeKeys.has(key) || highlightEdgeKeys.has(keyRev))
                ? "rgba(245,158,11,0.9)"
                : "rgba(147,197,253,0.08)"
            }}
            linkWidth={(link) => {
              if (highlightEdgeKeys.size === 0) return 1
              const key = `${link.source?.id ?? link.source}|${link.target?.id ?? link.target}`
              const keyRev = `${link.target?.id ?? link.target}|${link.source?.id ?? link.source}`
              return (highlightEdgeKeys.has(key) || highlightEdgeKeys.has(keyRev)) ? 2.5 : 0.5
            }}
            linkDirectionalArrowLength={(link) => {
              if (highlightEdgeKeys.size === 0) return 0
              const key = `${link.source?.id ?? link.source}|${link.target?.id ?? link.target}`
              return highlightEdgeKeys.has(key) ? 4 : 0
            }}
            linkDirectionalArrowColor={() => "rgba(245,158,11,0.9)"}
            linkLabel={link => link.relation || ""}
            linkCanvasObjectMode={() => "after"}
            linkCanvasObject={(link, ctx, globalScale) => {
              if (globalScale < 2.5) return
              const src = link.source
              const tgt = link.target
              if (!src?.x || !tgt?.x) return
              const mx = (src.x + tgt.x) / 2
              const my = (src.y + tgt.y) / 2
              const label = link.relation || ""
              if (!label) return
              const fontSize = Math.max(8 / globalScale, 2)
              ctx.font = `${fontSize}px Inter, sans-serif`
              ctx.textAlign = "center"
              ctx.textBaseline = "middle"
              ctx.fillStyle = "rgba(75,85,99,0.85)"
              ctx.fillText(label.replace(/_/g, " "), mx, my)
            }}
            backgroundColor="#f3f4f6"
            onNodeClick={handleNodeClick}
            onBackgroundClick={handlePaneClick}
            cooldownTicks={200}
            d3AlphaDecay={0.008}
            d3VelocityDecay={0.4}
            onEngineStop={() => {
              if (graphRef.current) graphRef.current.zoomToFit(400, 40)
            }}
            width={graphWidth}
            height={graphHeight}
          />

          {/* Node Detail Tooltip Overlay */}
          {selectedNode && selectedDetailsNode && (
            <div
              className="node-tooltip"
              style={{
                left: tooltipPos.x,
                top: tooltipPos.y,
                position: "absolute",
                pointerEvents: "auto",
                width: "320px",
                maxHeight: "520px",
                overflowY: "auto",
                zIndex: 20,
              }}
            >
              {/* Header row: entity type badge + close button */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                <div>
                  <span style={{ fontSize: 10, fontWeight: 700, background: TYPE_COLORS[selectedDetailsNode.type] || "#e5e7eb",
                    color: "#1f2937", borderRadius: 4, padding: "2px 6px", letterSpacing: 0.5 }}>
                    {selectedDetailsNode.type || "Entity"}
                  </span>
                  <h3 style={{ margin: "6px 0 0", fontSize: 14, wordBreak: "break-all" }}>
                    {selectedDetailsNode.label || selectedDetailsNode.id}
                  </h3>
                </div>
                <button onClick={() => { setSelectedNode(null); setSelectedDetails(null) }}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#9ca3af", fontSize: 18, lineHeight: 1 }}>✕</button>
              </div>

              {/* All node properties */}
              {Object.entries(selectedDetailsNode)
                .filter(([k]) => !["type", "label", "id"].includes(k) && selectedDetailsNode[k] !== "")
                .slice(0, 14)
                .map(([k, v]) => (
                  <div key={k} className="tooltip-row">
                    <span style={{ color: "#6b7280", textTransform: "capitalize" }}>{k.replace(/_/g, " ")}:</span>
                    <span>{v !== null && v !== undefined && String(v) !== "" ? String(v) : <em style={{ color: "#9ca3af" }}>—</em>}</span>
                  </div>
                ))}

              {/* Expand Neighborhood button */}
              {neighbors.length > 0 && (
                <button
                  onClick={() => expandNeighborhood(selectedNode, neighbors)}
                  style={{
                    marginTop: 12, width: "100%", padding: "7px 0",
                    background: expandMode ? "#fef3c7" : "#eff6ff",
                    border: `1px solid ${expandMode ? "#fde68a" : "#bfdbfe"}`,
                    borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
                    color: expandMode ? "#92400e" : "#1d4ed8",
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6
                  }}
                >
                  {expandMode ? "⬡" : "⬡"} {expandMode ? "Neighborhood Active" : "Expand Neighborhood"}
                  <span style={{ background: expandMode ? "#fde68a" : "#bfdbfe", borderRadius: 10, padding: "1px 7px", fontSize: 11 }}>
                    {neighbors.length}
                  </span>
                </button>
              )}

              {/* Clickable neighbors list */}
              {neighbors.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, color: "#6b7280", fontWeight: 700, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Relationships
                  </div>
                  {neighbors.slice(0, 8).map((n, i) => (
                    <div
                      key={i}
                      onClick={() => navigateToNode(String(n.id))}
                      style={{
                        display: "flex", alignItems: "center", gap: 8, padding: "5px 8px",
                        borderRadius: 6, cursor: "pointer", marginBottom: 3,
                        background: selectedNode === String(n.id) ? "#eff6ff" : "transparent",
                        transition: "background 0.15s"
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "#f9fafb"}
                      onMouseLeave={e => e.currentTarget.style.background = selectedNode === String(n.id) ? "#eff6ff" : "transparent"}
                    >
                      <span style={{
                        display: "inline-block", width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                        background: TYPE_COLORS[graphData.nodes.find(nd => nd.id === String(n.id))?.type] || "#e5e7eb"
                      }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 1 }}>
                          {(n.relation || "→").replace(/_/g, " ")}
                        </div>
                        <div style={{ fontSize: 12, color: "#374151", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {n.label || n.id}
                        </div>
                      </div>
                      <span style={{ color: "#9ca3af", fontSize: 12 }}>›</span>
                    </div>
                  ))}
                  {neighbors.length > 8 && (
                    <div style={{ fontSize: 11, color: "#9ca3af", textAlign: "center", marginTop: 4 }}>
                      +{neighbors.length - 8} more connections
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Chat Pane */}
        <div className="chat-pane">
          <div className="chat-header">
            <h2>Chat with Graph</h2>
            <p>Order to Cash</p>
          </div>

          <div className="chat-messages">
            {messages.map((m, i) => (
              <div key={i} className={`message-group ${m.role}`}>
                {m.role === "bot" ? (
                  <>
                    <div className="message-author">
                      <div className="ai-avatar">D</div>
                      <div className="author-info">
                        <span className="author-name">Dodge AI</span>
                        <span className="author-role">Graph Agent</span>
                      </div>
                    </div>
                    <div className="message-bubble bot-msg">
                      {m.text || (m.streaming ? "" : "—")}
                      {/* Streaming cursor — blinks while tokens arrive */}
                      {m.streaming && (
                        <span style={{
                          display: "inline-block", width: 2, height: "1em",
                          background: "#374151", verticalAlign: "text-bottom",
                          marginLeft: 2, animation: "blink 0.8s step-end infinite"
                        }} />
                      )}
                      {m.sql && <div className="sql-block">{m.sql}</div>}
                      {/* Data table — ground the answer in actual query results */}
                      {m.data && m.data.length > 0 && (() => {
                        const cols = Object.keys(m.data[0])
                        const rows = m.data.slice(0, 8)
                        return (
                          <div style={{ marginTop: 10, overflowX: "auto" }}>
                            <div style={{ fontSize: 10, color: "#6b7280", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ background: "#dcfce7", color: "#16a34a", borderRadius: 10, padding: "1px 7px", fontWeight: 700 }}>
                                {m.row_count} row{m.row_count !== 1 ? "s" : ""} found
                              </span>
                              from database
                            </div>
                            <table style={{ fontSize: 10, borderCollapse: "collapse", width: "100%", minWidth: 200 }}>
                              <thead>
                                <tr>
                                  {cols.map(c => (
                                    <th key={c} style={{ padding: "3px 6px", background: "#f1f5f9", borderBottom: "1px solid #e2e8f0", textAlign: "left", fontWeight: 600, color: "#475569", whiteSpace: "nowrap" }}>
                                      {c.replace(/_/g, " ")}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {rows.map((row, ri) => (
                                  <tr key={ri} style={{ background: ri % 2 === 0 ? "white" : "#f8fafc" }}>
                                    {cols.map(c => (
                                      <td key={c} style={{ padding: "3px 6px", borderBottom: "1px solid #f1f5f9", color: "#374151", whiteSpace: "nowrap", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>
                                        {row[c] !== null && row[c] !== undefined ? String(row[c]) : <em style={{ color: "#9ca3af" }}>—</em>}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {m.row_count > 8 && (
                              <div style={{ fontSize: 10, color: "#9ca3af", textAlign: "center", marginTop: 4 }}>
                                +{m.row_count - 8} more rows not shown
                              </div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="message-author">
                      <div className="author-info" style={{ marginLeft: "auto", textAlign: "right" }}>
                        <span className="author-name">You</span>
                      </div>
                      <div className="user-avatar">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                          <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                      </div>
                    </div>
                    <div className="message-bubble user-msg">{m.text}</div>
                  </>
                )}
              </div>
            ))}
            {loading && (
              <div className="message-group bot">
                <div className="message-author">
                  <div className="ai-avatar">D</div>
                  <div className="author-info">
                    <span className="author-name">Dodge AI</span>
                    <span className="author-role">Graph Agent</span>
                  </div>
                </div>
                <div className="message-bubble bot-msg" style={{ color: "#9ca3af" }}>Typing...</div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="chat-input-wrapper">
            <div className="chat-input-box">
              <div className="input-status">
                <span className="status-dot"></span>
                Dodge AI is awaiting instructions
              </div>
              <div className="text-area-wrapper">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  placeholder="Analyze anything"
                  disabled={loading}
                />
                <button
                  className={`send-btn ${input.trim() ? "active" : ""}`}
                  onClick={handleSend}
                  disabled={loading || !input.trim()}
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
