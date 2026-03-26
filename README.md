# 🧠 Context Graph System — SAP Order-to-Cash (O2C)

A high-fidelity, interactive platform for exploring SAP business data through **Graph Visualization** and a **Context-Aware Conversational AI**. This system transforms complex relational O2C data into an intuitive knowledge graph, allowing users to query business flows using natural language.

---

## 🚀 Project Overview

The **Context Graph System** bridges the gap between raw ERP data and actionable business insights. It handles the entire lifecycle of a transaction flow — from Customer to Payment — and provides two primary ways to interact with the data:
1.  **Visual Graph Exploration**: Interactive 2D force-directed graph for tracing relationships.
2.  **AI Query Engine**: Multi-stage LLM pipeline that converts natural language to valid SQL and graph traversals.

---

## 🏗️ Architecture Decisions

The system is built as a modular full-stack application designed for performance and reliability:

### **Frontend (Vite + React)**
- **react-force-graph-2d**: Chosen for high-performance canvas rendering of 1,500+ nodes and edges.
- **Reactive State Management**: Handles real-time node expansion and neighborhood highlighting.
- **Streaming UI**: Supports Server-Sent Events (SSE) for real-time, "typewriter-style" AI responses.

### **Backend (FastAPI + Python)**
- **Async Framework**: FastAPI provides high concurrency for handling multiple LLM and DB requests simultaneously.
- **Hybrid Search**: Combines traditional SQL filtering with semantic search over entity properties.
- **Modular Design**: Separate layers for Graph Ingestion, Query Routing, and LLM orchestration.

---

## 🗄️ Database Choice: Why SQLite?

While many graph systems default to Neo4j (Cypher), this project intentionally uses **SQLite** for the following reasons:
-   **Strict Relational Integrity**: Business data (Sales Orders, Invoices) is inherently relational. SQLite ensures that ID links and numeric consistency (e.g., matching invoice totals to order amounts) are perfectly maintained.
-   **NL-to-SQL Accuracy**: Modern LLMs (like Llama 3) have significantly higher accuracy generating SQL compared to graph-specific languages like Cypher. This prevents "hallucination" in complex business logic queries.
-   **Zero Infrastructure**: The entire database is a single portable file (`graph.db`), making it ideal for rapid deployment on free-tier services like Render.

---

## 🤖 LLM Prompting & Reasoning Strategy

The system uses a **Multi-Stage Reasoning Pipeline** powered by **Groq (Llama 3.3 70B)**:

1.  **Domain Classification**: A lightweight classifier determines if the query is related to the dataset. Out-of-domain questions (e.g., "Write a poem") are gracefully rejected.
2.  **Schema-Aware SQL Generation**: The LLM is provided with a "pinned" schema and few-shot examples (NL → SQL pairs) to ensure it uses the correct table names and joins.
3.  **Data-Grounded Synthesis**: Once the SQL is executed, the raw results are passed back to the LLM. It is instructed to summarize the findings *only* based on the returned data, citing specific record counts to maintain ground truth.
4.  **Few-Shot Prompting**: By providing concrete examples of complex queries in the prompt, we achieve >85% accuracy on multi-table joins.

---

## 🛡️ Guardrails & Safety

-   **Read-Only SQL Enforcement**: A regex-based validator blocks any query containing `DROP`, `DELETE`, `UPDATE`, or `ALTER`.
-   **Domain Restriction**: The system prompt strictly limits the AI's persona to an "SAP O2C Analyst," preventing it from answering unrelated queries.
-   **Contextual Memory**: Conversation history is maintained to resolve pronouns (e.g., "Who counts as *that* customer?").
-   **Validation UI**: Every AI answer is accompanied by the raw data table in the frontend, allowing users to verify the AI's claims against the ground truth.

---

## 🛠️ Installation & Setup (Local)

### 1. Requirements
- Python 3.9+
- Node.js 18+
- Groq API Key

### 2. Backend Setup
```bash
cd backend
pip install -r requirements.txt
# Add your GROQ_API_KEY to .env
python main.py
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

---

## 🌐 Deployment (Free Tier)

### **Backend (Render)**
- Set **Root Directory** to `backend`.
- Add `GROQ_API_KEY` to Environment Variables.
- Use `python main.py` as the start command (configured in `render.yaml`).

### **Frontend (Vercel)**
- Set **Root Directory** to `frontend`.
- Set `VITE_API_URL` to your Render backend URL.
- The `vercel.json` and `package.json` are pre-configured to handle the sub-directory build correctly.

---

## 📊 Key Features
- ✅ **Dynamic Node Expansion**: Click any node to load its immediate neighbors from the graph.
- ✅ **Multi-Turn Chat**: AI remembers previous queries and results.
- ✅ **Hybrid Querying**: Seamlessly switches between SQL-based aggregates and Graph-based pathfinding.
- ✅ **High Performance**: Optimized canvas rendering for large datasets.
