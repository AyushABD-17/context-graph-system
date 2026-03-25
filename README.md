# SAP Order-to-Cash Graph Visualization & AI Query System

A high-fidelity, interactive platform for exploring SAP business data through graph visualization and a context-aware conversational AI.

## 🚀 Live Demo & Submission
- **Local URL**: [http://localhost:5173](http://localhost:5173)
- **Functional Proof**: [Walkthrough & Video Demo](file:///C:/Users/CT_USER/.gemini/antigravity/brain/629a9b18-62e7-43ad-8850-f371dcb13589/walkthrough.md)

---

## 🏗️ Architecture Decisions

### **Frontend**
- **React + Vite**: Chosen for performance and modern developer experience.
- **react-force-graph-2d**: Used for high-performance canvas rendering of 1,500+ nodes. Custom `canvasPaint` is utilized for edge labels and neighborhood highlighting to ensure smooth UX even during continuous interaction.
- **SSE (Server-Sent Events)**: Implemented for a "ChatGPT-style" streaming response experience.

### **Backend**
- **FastAPI**: Selected for its asynchronous capabilities and native support for streaming responses via `StreamingResponse`.
- **SQLite**: Used for both the graph data and the conversation memory. It provides a strict relational schema that the LLM can reliably query.
- **Graph Indexing**: A dual-index system (JSON for visual graph, SQLite for data queries, and a custom property index for real-time highlighting) ensures sub-second response times.

---

## 🗄️ Database Choice
The system uses **SQLite** for several key reasons:
1. **Strict Entity-Relationship Modeling**: Business data like Sales Orders and deliveries require structured schemas to calculate aggregates (e.g., "Total Order Amount").
2. **NL-to-SQL Reliability**: LLMs (like Llama 3) excel at SQL generation when provided with a clear schema, making it more reliable than graph-specific query languages (like Cypher) for complex business logic.
3. **Portability**: The entire dataset is self-contained in `graph.db`, requiring zero infrastructure overhead for the user.

---

## 🤖 LLM Prompting Strategy

The system uses a **multi-stage prompting strategy** powered by Llama 3.3 70B:
1. **Intent Classification**: Categorizes queries into "Standard SQL", "Navigation/Search", or "System Metadata".
2. **Contextual SQL Generation**: Generates constrained SQLite queries by injecting table schemas and entity relationships into the system prompt.
3. **Data-Grounded Synthesis**: After SQL execution, the raw result rows are fed back to the LLM. The LLM is instructed to answer **only** based on the provided data, explicitly citing record counts to ensure accuracy.

---

## 🛡️ Guardrails

To ensure safety and relevance, the following guardrails are implemented:
1. **Topic Guard**: A prerequisite intent check blocks questions unrelated to SAP or Order-to-Cash.
2. **Multi-Turn Context Resolution**: The system maintains conversation history to resolve pronouns (e.g., "Who counts as *that* customer?").
3. **Execution Safety**: All generated SQL is read-only.
4. **Data Verification**: Every AI answer is accompanied by a **live data table** in the UI, proving that the response is backed by ground truth database records.

---

## 🌐 Deployment Instructions (Free Tier)

### 1. **Backend (Render)**
- **Source**: Connect your GitHub repository.
- **Root Directory**: `backend`
- **Environment Variable**: Add `GROQ_API_KEY`.
- **Render.yaml**: The configuration is included in `backend/render.yaml`.
- **Live URL**: Once deployed, copy your Render service URL (e.g., `https://sap-graph-backend.onrender.com`).

### 2. **Frontend (Vercel/Netlify)**
- **Source**: Connect the same repository.
- **Root Directory**: `frontend`
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Environment Variable**: Set `VITE_API_URL` to your Render backend URL.
- **Live URL**: Share the resulting Vercel URL with your users!

> [!CAUTION]
> **Ephemeral Storage**: On Render’s free tier, the SQLite database (`memory.db`) will reset every time the service restarts.

---

## 🛠️ Installation & Running (Local)

1. **Backend**:
   ```bash
   cd backend
   pip install -r requirements.txt
   python main.py
   ```
2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
