import os
import sqlite3
import json
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY", "dummy_key_to_permit_server_bootup"))

def call_llm(prompt: str) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()

def is_on_topic(message: str, history: list = None) -> bool:
    """
    Returns True if the message is about the SAP Order-to-Cash dataset,
    OR if it's a follow-up to a prior data-related conversation.
    """
    keywords = [
        "order", "delivery", "billing", "invoice", "payment", "customer", "product",
        "plant", "partner", "journal", "sales", "material", "shipment", "document",
        "cancellation", "schedule", "receivable", "item", "quantity", "amount", "date",
        "who", "which", "how many", "what", "show", "list", "find", "top", "total",
        "status", "incomplete", "pending", "complete", "summary"
    ]
    msg_lower = message.lower()
    # Direct keyword match
    for kw in keywords:
        if kw in msg_lower:
            return True
    # If there's prior conversation history, treat as a follow-up (likely relevant)
    if history and len(history) > 0:
        return True
    return False

def generate_sql(question: str, history: list = None) -> str:
    # Build conversation context for follow-up queries
    history_text = ""
    if history:
        recent = history[-4:]  # last 2 exchanges
        for turn in recent:
            role = "User" if turn["role"] == "user" else "Assistant"
            history_text += f"{role}: {turn['text']}\n"

    prompt = f"""You are a SQLite expert. Generate a precise SELECT query for a SAP Order-to-Cash database.

SCHEMA:
  sales_order_headers: (sales_order, sales_order_type, sold_to_party, creation_date, total_net_amount, transaction_currency, overall_delivery_status)
  sales_order_items: (sales_order, sales_order_item, material, requested_quantity, net_amount, storage_location, production_plant)
  sales_order_schedule_lines: (sales_order, sales_order_item, schedule_line, delivery_date, order_quantity)
  billing_document_headers: (billing_document, billing_document_type, creation_date, billing_document_date, total_net_amount, transaction_currency, company_code, sold_to_party)
  billing_document_items: (billing_document, billing_document_item, material, billing_quantity, net_amount, reference_sd_document, reference_sd_document_item)
  billing_document_cancellations: (billing_document, cancellation_billing_document, cancellation_date)
  outbound_delivery_headers: (delivery_document, creation_date, delivery_block_reason, overall_goods_movement_status)
  outbound_delivery_items: (delivery_document, delivery_document_item, reference_sd_document, reference_sd_document_item, actual_delivery_quantity, plant)
  journal_entry_items_accounts_receivable: (company_code, fiscal_year, accounting_document, gl_account, reference_document, amount_in_company_code_currency, posting_date, customer)
  payments_accounts_receivable: (company_code, fiscal_year, accounting_document, clearing_date, clearing_accounting_document, amount_in_company_code_currency, customer, invoice_reference)
  business_partners: (business_partner, customer, business_partner_full_name, business_partner_grouping, first_name, last_name, organization_bp_name1)
  business_partner_addresses: (business_partner, address_id, street_name, city_name, postal_code, country)
  products: (product, product_type, product_group, base_unit, net_weight, gross_weight, industry_sector)
  product_descriptions: (product, language, product_description)
  plants: (plant, plant_name, country, city_name)

CRITICAL RULES:
1. Return ONLY the raw SQLite SELECT query — no markdown, no backticks, no explanation
2. ALWAYS use a WHERE clause when the question mentions a specific document number, customer ID, or any specific value
3. For "find journal entry linked to [DOC_NUMBER]":
   SELECT company_code, fiscal_year, accounting_document, reference_document
   FROM journal_entry_items_accounts_receivable
   WHERE reference_document = '[DOC_NUMBER]'
   NOTE: billing documents link to journal entries via the `reference_document` column
4. For "find sales order items for order [X]": use WHERE sales_order = '[X]'
5. For aggregation queries (count, sum, max): no LIMIT needed
6. For list queries without a specific filter: add LIMIT 100
7. Always JOIN properly when crossing tables — always return the relevant ID columns
8. Use prior conversation context to resolve pronouns like "that customer", "those orders", "the same one"

{f'CONVERSATION CONTEXT (use to resolve follow-up references):{chr(10)}{history_text}' if history_text else ''}
User question: {question}"""

    response_text = call_llm(prompt)
    sql = response_text.replace("```sql", "").replace("```", "").strip()
    return sql

def execute_sql(sql: str, conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        columns = [description[0] for description in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        retry_prompt = f"This SQL gave an error: {e}. Original SQL: {sql}. Fix it and return only the corrected SQL."
        try:
            response_text = call_llm(retry_prompt)
            new_sql = response_text.replace("```sql", "").replace("```", "").strip()
            cursor.execute(new_sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception:
            return []

def generate_answer(question: str, sql: str, data: list, history: list = None) -> str:
    history_text = ""
    if history:
        recent = history[-4:]
        for turn in recent:
            role = "User" if turn["role"] == "user" else "Assistant"
            history_text += f"{role}: {turn['text']}\n"

    total_rows = len(data)
    sample = data[:30]  # show up to 30 rows in prompt for grounding

    prompt = f"""You are a SAP business analyst answering questions about Order-to-Cash data.

{f'CONVERSATION HISTORY:{chr(10)}{history_text}' if history_text else ''}
Question: {question}
SQL executed: {sql}
Total rows returned: {total_rows}
Data sample (up to 30 rows): {json.dumps(sample, indent=2)}

Rules:
- Answer in 2-5 sentences using ONLY the data above
- Always mention the exact count of records found (e.g. "Found 42 sales orders...")
- If results are empty, say exactly that — do not guess or invent
- Do NOT make up numbers, names, or facts not present in the data
- Reference specific values from the data (document IDs, amounts, dates, names)"""

    response_text = call_llm(prompt)
    return response_text

def build_node_property_index(graph_data: dict) -> dict:
    """
    Pre-build an index: (field_name_lower, str_value) -> list of node IDs.
    This allows O(1) lookup of which nodes contain a given SAP field=value pair.
    """
    index = {}
    skip_fields = {"id", "type", "label"}
    for n in graph_data.get("nodes", []):
        nid = str(n["id"])
        for field, val in n.items():
            if field in skip_fields or val is None:
                continue
            key = (field.lower(), str(val).strip())
            if key not in index:
                index[key] = []
            index[key].append(nid)
    return index


def extract_node_ids_from_data(data: list, graph_data: dict, _index_cache: dict = {}) -> list:
    """
    Maps SQL result rows to graph node IDs by matching column+value pairs
    against the node property index. Supports any SAP column name.
    """
    # Build or reuse the index
    cache_key = id(graph_data)
    if cache_key not in _index_cache:
        _index_cache.clear()
        _index_cache[cache_key] = build_node_property_index(graph_data)
    index = _index_cache[cache_key]

    matched = set()
    for row in data[:100]:
        for col, val in row.items():
            if val is None:
                continue
            key = (col.lower(), str(val).strip())
            if key in index:
                for nid in index[key]:
                    matched.add(nid)
    return list(matched)



def find_connecting_edges(node_ids: list, graph_data: dict) -> list:
    """Returns edge IDs (as source-target strings) that connect the highlighted node set."""
    id_set = set(node_ids)
    connecting = []
    for e in graph_data.get("edges", []):
        src = str(e["source"])
        tgt = str(e["target"])
        if src in id_set and tgt in id_set:
            connecting.append({"source": src, "target": tgt, "relation": e.get("relation", "")})
    return connecting


def extract_node_ids_with_index(data: list, index: dict) -> list:
    """Uses a pre-built property index to match SQL result rows to node IDs."""
    matched = set()
    for row in data[:100]:
        for col, val in row.items():
            if val is None:
                continue
            key = (col.lower(), str(val).strip())
            if key in index:
                for nid in index[key]:
                    matched.add(nid)
    return list(matched)


def process(message: str, conn: sqlite3.Connection, graph_data: dict = None, node_index: dict = None, history: list = None) -> dict:
    try:
        if not is_on_topic(message, history):
            return {
                "answer": "This system is designed to answer questions about the SAP Order-to-Cash dataset only.",
                "sql": None,
                "data": [],
                "highlighted_nodes": [],
                "highlighted_edges": []
            }

        sql = generate_sql(message, history)
        data = execute_sql(sql, conn)
        answer = generate_answer(message, sql, data, history)

        highlighted_nodes = []
        highlighted_edges = []
        if data:
            if node_index:
                highlighted_nodes = extract_node_ids_with_index(data, node_index)
            elif graph_data:
                highlighted_nodes = extract_node_ids_from_data(data, graph_data)

            if highlighted_nodes:
                highlighted_edges = find_connecting_edges(highlighted_nodes, graph_data or {})

        return {
            "answer": answer,
            "sql": sql,
            "data": data[:100],  # cap data returned to frontend at 100 rows
            "row_count": len(data),
            "highlighted_nodes": highlighted_nodes,
            "highlighted_edges": highlighted_edges
        }
    except Exception as e:
        return {
            "answer": f"Something went wrong: {e}",
            "sql": None,
            "data": [],
            "row_count": 0,
            "highlighted_nodes": [],
            "highlighted_edges": []
        }
