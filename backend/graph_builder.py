"""
graph_builder.py — Strict Order-to-Cash Entity-Relationship Graph

Node Types:
  Customer           business_partner (PK)
  Address            business_partner + address_id (PK)
  SalesOrder         sales_order (PK)
  SalesOrderItem     sales_order + sales_order_item (composite PK)
  ScheduleLine       sales_order + item + schedule_line (composite PK)
  Delivery           delivery_document (PK)
  DeliveryItem       delivery_document + delivery_document_item (composite PK)
  Invoice            billing_document (PK)
  InvoiceItem        billing_document + billing_document_item (composite PK)
  Cancellation       billing_document (cancellation record)
  JournalEntry       company_code + fiscal_year + accounting_document (composite PK)
  Payment            company_code + fiscal_year + accounting_document (composite PK)
  Product            product (PK)
  Plant              plant (PK)

Edge Flow (strict O2C):
  Customer ──placed_order──► SalesOrder
  SalesOrder ──has_item──► SalesOrderItem
  SalesOrderItem ──has_schedule_line──► ScheduleLine
  SalesOrderItem ──delivered_as──► DeliveryItem
  DeliveryItem ──part_of_delivery──► Delivery
  Delivery ──shipped_from──► Plant
  SalesOrderItem ──billed_as──► InvoiceItem
  InvoiceItem ──part_of_invoice──► Invoice
  Customer ──billed_to──► Invoice
  Invoice ──triggers_journal──► JournalEntry
  JournalEntry ──cleared_by──► Payment
  Invoice ──cancelled_by──► Cancellation
  Product ──ordered_as──► SalesOrderItem
  Customer ──has_address──► Address
"""

import networkx as nx
import pandas as pd
import sqlite3
import json
import pickle
from pathlib import Path

DB_PATH  = Path("graph.db")
GRAPH_PKL  = Path("graph.pkl")
GRAPH_JSON = Path("graph.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_tables(conn: sqlite3.Connection) -> dict:
    tables = {}
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    for (name,) in cursor.fetchall():
        df = pd.read_sql_query(f"SELECT * FROM {name}", conn)
        tables[name] = df
        print(f"  Loaded {name}: {df.shape[0]} rows × {df.shape[1]} cols")
    return tables


def col(df: pd.DataFrame, candidates: list) -> str | None:
    """Return the first column name that matches one of the candidates (case-insensitive)."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def node_attrs(row: pd.Series, type_: str, label: str) -> dict:
    """Convert a DataFrame row to a node attribute dict, keeping ALL fields."""
    attrs = {"type": type_, "label": label}
    for k, v in row.items():
        if pd.isna(v):
            attrs[k] = ""
        elif isinstance(v, (int, float)):
            attrs[k] = v
        else:
            attrs[k] = str(v)
    return attrs


def safe_edge(G: nx.DiGraph, src: str, tgt: str, relation: str):
    if src and tgt and G.has_node(src) and G.has_node(tgt):
        G.add_edge(src, tgt, relation=relation)


# ---------------------------------------------------------------------------
# NODE BUILDERS  (each returns a {lookup_key: node_id} map for edge building)
# ---------------------------------------------------------------------------

def add_customers(G, tables):
    """Customer node per business_partner row."""
    t = "business_partners"
    if t not in tables:
        return {}
    df = tables[t]
    pk = col(df, ["business_partner"])
    name_col = col(df, ["business_partner_full_name", "organization_bp_name1"])
    mp = {}
    for _, row in df.iterrows():
        if pd.isna(row.get(pk, None)):
            continue
        pk_val = str(row[pk])
        nid = f"customer_{pk_val}"
        label = str(row[name_col]) if name_col and pd.notna(row[name_col]) else pk_val
        G.add_node(nid, **node_attrs(row, "Customer", label))
        mp[pk_val] = nid
    print(f"  Customers: {len(mp)}")
    return mp


def add_addresses(G, tables, customer_map):
    """Address node per business_partner_addresses row."""
    t = "business_partner_addresses"
    if t not in tables:
        return {}
    df = tables[t]
    bp_c = col(df, ["business_partner"])
    addr_c = col(df, ["address_id"])
    city_c = col(df, ["city_name"])
    mp = {}
    for _, row in df.iterrows():
        bp_val = str(row[bp_c]) if bp_c else ""
        addr_val = str(row[addr_c]) if addr_c else str(_)
        nid = f"address_{bp_val}_{addr_val}"
        label = str(row[city_c]) if city_c and pd.notna(row[city_c]) else addr_val
        G.add_node(nid, **node_attrs(row, "Address", label))
        mp[(bp_val, addr_val)] = nid
        # Edge: Customer → Address
        if bp_val in customer_map:
            safe_edge(G, customer_map[bp_val], nid, "has_address")
    print(f"  Addresses: {len(mp)}")
    return mp


def add_products(G, tables):
    """Product node per products row."""
    t = "products"
    if t not in tables:
        return {}
    df = tables[t]
    pk = col(df, ["product"])
    mp = {}
    for _, row in df.iterrows():
        pk_val = str(row[pk]) if pk else str(_)
        nid = f"product_{pk_val}"
        G.add_node(nid, **node_attrs(row, "Product", pk_val))
        mp[pk_val] = nid
    print(f"  Products: {len(mp)}")
    return mp


def add_plants(G, tables):
    """Plant node per plants row."""
    t = "plants"
    if t not in tables:
        return {}
    df = tables[t]
    pk = col(df, ["plant"])
    name_c = col(df, ["plant_name"])
    mp = {}
    for _, row in df.iterrows():
        pk_val = str(row[pk]) if pk else str(_)
        nid = f"plant_{pk_val}"
        label = str(row[name_c]) if name_c and pd.notna(row[name_c]) else pk_val
        G.add_node(nid, **node_attrs(row, "Plant", label))
        mp[pk_val] = nid
    print(f"  Plants: {len(mp)}")
    return mp


def add_sales_orders(G, tables, customer_map):
    """SalesOrder node per sales_order_headers row."""
    t = "sales_order_headers"
    if t not in tables:
        return {}
    df = tables[t]
    pk = col(df, ["sales_order"])
    sold_to = col(df, ["sold_to_party"])
    mp = {}
    for _, row in df.iterrows():
        pk_val = str(row[pk]) if pk else str(_)
        nid = f"sales_order_{pk_val}"
        G.add_node(nid, **node_attrs(row, "SalesOrder", pk_val))
        mp[pk_val] = nid
        # Edge: Customer → SalesOrder
        if sold_to and pd.notna(row.get(sold_to)):
            bp_val = str(row[sold_to])
            if bp_val in customer_map:
                safe_edge(G, customer_map[bp_val], nid, "placed_order")
    print(f"  SalesOrders: {len(mp)}")
    return mp


def add_sales_order_items(G, tables, so_map, product_map):
    """SalesOrderItem node per sales_order_items row. ID = salesorderitem_{so}_{item}."""
    t = "sales_order_items"
    if t not in tables:
        return {}
    df = tables[t]
    so_c  = col(df, ["sales_order"])
    itm_c = col(df, ["sales_order_item"])
    mat_c = col(df, ["material"])
    mp = {}
    for _, row in df.iterrows():
        so_val  = str(row[so_c])  if so_c  else ""
        itm_val = str(row[itm_c]) if itm_c else str(_)
        mat_val = str(row[mat_c]) if mat_c and pd.notna(row.get(mat_c)) else itm_val
        nid = f"so_item_{so_val}_{itm_val}"
        G.add_node(nid, **node_attrs(row, "SalesOrderItem", mat_val))
        key = (so_val, itm_val)
        mp[key] = nid
        # Also index stripped variant (leading zeros removed)
        mp[(so_val, itm_val.lstrip("0") or "0")] = nid
        # Edge: SalesOrder → SalesOrderItem
        if so_val in so_map:
            safe_edge(G, so_map[so_val], nid, "has_item")
        # Edge: Product → SalesOrderItem
        if mat_val in product_map:
            safe_edge(G, product_map[mat_val], nid, "ordered_as")
    print(f"  SalesOrderItems: {len(df)}")
    return mp


def add_schedule_lines(G, tables, si_map):
    """ScheduleLine node per sales_order_schedule_lines row."""
    t = "sales_order_schedule_lines"
    if t not in tables:
        return {}
    df = tables[t]
    so_c   = col(df, ["sales_order"])
    itm_c  = col(df, ["sales_order_item"])
    line_c = col(df, ["schedule_line"])
    date_c = col(df, ["delivery_date"])
    for _, row in df.iterrows():
        so_val   = str(row[so_c])   if so_c   else ""
        itm_val  = str(row[itm_c])  if itm_c  else ""
        line_val = str(row[line_c]) if line_c else str(_)
        date_val = str(row[date_c]) if date_c and pd.notna(row.get(date_c)) else ""
        nid = f"schedule_{so_val}_{itm_val}_{line_val}"
        label = date_val if date_val else line_val
        G.add_node(nid, **node_attrs(row, "ScheduleLine", label))
        # Edge: SalesOrderItem → ScheduleLine
        for key in [(so_val, itm_val), (so_val, itm_val.lstrip("0") or "0")]:
            if key in si_map:
                safe_edge(G, si_map[key], nid, "has_schedule_line")
                break
    print(f"  ScheduleLines: {len(df)}")


def add_deliveries(G, tables, plant_map):
    """Delivery node per outbound_delivery_headers row."""
    t = "outbound_delivery_headers"
    if t not in tables:
        return {}
    df = tables[t]
    pk     = col(df, ["delivery_document"])
    plt_c  = col(df, ["shipping_point", "plant"])
    mp = {}
    for _, row in df.iterrows():
        pk_val = str(row[pk]) if pk else str(_)
        nid = f"delivery_{pk_val}"
        G.add_node(nid, **node_attrs(row, "Delivery", pk_val))
        mp[pk_val] = nid
        # Edge: Delivery → Plant
        if plt_c and pd.notna(row.get(plt_c)):
            plt_val = str(row[plt_c])
            if plt_val in plant_map:
                safe_edge(G, nid, plant_map[plt_val], "shipped_from")
    print(f"  Deliveries: {len(mp)}")
    return mp


def add_delivery_items(G, tables, delivery_map, si_map):
    """DeliveryItem node per outbound_delivery_items row."""
    t = "outbound_delivery_items"
    if t not in tables:
        return {}
    df = tables[t]
    del_c  = col(df, ["delivery_document"])
    ditm_c = col(df, ["delivery_document_item"])
    ref_c  = col(df, ["reference_sd_document"])
    ritm_c = col(df, ["reference_sd_document_item"])
    plt_c  = col(df, ["plant"])
    mp = {}
    for _, row in df.iterrows():
        del_val  = str(row[del_c])  if del_c  else ""
        ditm_val = str(row[ditm_c]) if ditm_c else str(_)
        nid = f"del_item_{del_val}_{ditm_val}"
        G.add_node(nid, **node_attrs(row, "DeliveryItem", ditm_val))
        mp[(del_val, ditm_val)] = nid
        # Edge: DeliveryItem → Delivery
        if del_val in delivery_map:
            safe_edge(G, nid, delivery_map[del_val], "part_of_delivery")
        # Edge: SalesOrderItem → DeliveryItem
        if ref_c and ritm_c and pd.notna(row.get(ref_c)) and pd.notna(row.get(ritm_c)):
            ref_val  = str(row[ref_c])
            ritm_val = str(row[ritm_c])
            for key in [(ref_val, ritm_val), (ref_val, ritm_val.lstrip("0") or "0")]:
                if key in si_map:
                    safe_edge(G, si_map[key], nid, "delivered_as")
                    break
    print(f"  DeliveryItems: {len(df)}")
    return mp


def add_invoices(G, tables, customer_map):
    """Invoice node per billing_document_headers row."""
    t = "billing_document_headers"
    if t not in tables:
        return {}
    df = tables[t]
    pk      = col(df, ["billing_document"])
    sold_c  = col(df, ["sold_to_party"])
    mp = {}
    for _, row in df.iterrows():
        pk_val = str(row[pk]) if pk else str(_)
        nid = f"invoice_{pk_val}"
        G.add_node(nid, **node_attrs(row, "Invoice", pk_val))
        mp[pk_val] = nid
        # Edge: Customer → Invoice
        if sold_c and pd.notna(row.get(sold_c)):
            bp_val = str(row[sold_c])
            if bp_val in customer_map:
                safe_edge(G, customer_map[bp_val], nid, "billed_to")
    print(f"  Invoices: {len(mp)}")
    return mp


def add_invoice_items(G, tables, invoice_map, si_map):
    """InvoiceItem node per billing_document_items row."""
    t = "billing_document_items"
    if t not in tables:
        return {}
    df = tables[t]
    bd_c   = col(df, ["billing_document"])
    bitm_c = col(df, ["billing_document_item"])
    ref_c  = col(df, ["reference_sd_document"])
    ritm_c = col(df, ["reference_sd_document_item"])
    mat_c  = col(df, ["material"])
    mp = {}
    for _, row in df.iterrows():
        bd_val   = str(row[bd_c])   if bd_c   else ""
        bitm_val = str(row[bitm_c]) if bitm_c else str(_)
        mat_val  = str(row[mat_c])  if mat_c and pd.notna(row.get(mat_c)) else bitm_val
        nid = f"inv_item_{bd_val}_{bitm_val}"
        G.add_node(nid, **node_attrs(row, "InvoiceItem", mat_val))
        mp[(bd_val, bitm_val)] = nid
        # Edge: InvoiceItem → Invoice
        if bd_val in invoice_map:
            safe_edge(G, nid, invoice_map[bd_val], "part_of_invoice")
        # Edge: SalesOrderItem → InvoiceItem
        if ref_c and ritm_c and pd.notna(row.get(ref_c)) and pd.notna(row.get(ritm_c)):
            ref_val  = str(row[ref_c])
            ritm_val = str(row[ritm_c])
            for key in [(ref_val, ritm_val), (ref_val, ritm_val.lstrip("0") or "0")]:
                if key in si_map:
                    safe_edge(G, si_map[key], nid, "billed_as")
                    break
    print(f"  InvoiceItems: {len(df)}")
    return mp


def add_cancellations(G, tables, invoice_map):
    """Cancellation node per billing_document_cancellations row."""
    t = "billing_document_cancellations"
    if t not in tables:
        return
    df = tables[t]
    bd_c   = col(df, ["billing_document"])
    canc_c = col(df, ["cancellation_billing_document"])
    date_c = col(df, ["cancellation_date"])
    for _, row in df.iterrows():
        bd_val   = str(row[bd_c])   if bd_c   else str(_)
        canc_val = str(row[canc_c]) if canc_c and pd.notna(row.get(canc_c)) else ""
        date_val = str(row[date_c]) if date_c and pd.notna(row.get(date_c)) else ""
        nid = f"cancellation_{bd_val}"
        G.add_node(nid, **node_attrs(row, "Cancellation", canc_val or bd_val))
        if bd_val in invoice_map:
            safe_edge(G, invoice_map[bd_val], nid, "cancelled_by")
    print(f"  Cancellations: {len(df)}")


def add_journal_entries(G, tables, invoice_map):
    """
    JournalEntry node per journal_entry_items_accounts_receivable row.
    Edge: Invoice → JournalEntry  (via reference_document = billing_document)
    """
    t = "journal_entry_items_accounts_receivable"
    if t not in tables:
        return {}
    df = tables[t]
    cc_c    = col(df, ["company_code"])
    fy_c    = col(df, ["fiscal_year"])
    acct_c  = col(df, ["accounting_document"])
    # The billing document reference is stored as reference_document
    ref_c   = col(df, ["reference_document", "billing_document"])
    mp = {}
    for _, row in df.iterrows():
        cc_val   = str(row[cc_c])   if cc_c   and pd.notna(row.get(cc_c))   else ""
        fy_val   = str(row[fy_c])   if fy_c   and pd.notna(row.get(fy_c))   else ""
        acct_val = str(row[acct_c]) if acct_c and pd.notna(row.get(acct_c)) else str(_)
        nid = f"journal_{cc_val}_{fy_val}_{acct_val}"
        G.add_node(nid, **node_attrs(row, "JournalEntry", acct_val))
        mp[(cc_val, fy_val, acct_val)] = nid
        # Edge: Invoice → JournalEntry  (billing_document ↔ reference_document)
        if ref_c and pd.notna(row.get(ref_c)):
            ref_val = str(row[ref_c])
            if ref_val in invoice_map:
                safe_edge(G, invoice_map[ref_val], nid, "triggers_journal")
    print(f"  JournalEntries: {len(df)}")
    return mp


def add_payments(G, tables, journal_map):
    """
    Payment node per payments_accounts_receivable row.
    Edge: JournalEntry → Payment  (via clearing_accounting_document = accounting_document)
    """
    t = "payments_accounts_receivable"
    if t not in tables:
        return
    df = tables[t]
    cc_c      = col(df, ["company_code"])
    fy_c      = col(df, ["fiscal_year"])
    acct_c    = col(df, ["accounting_document"])
    clear_c   = col(df, ["clearing_accounting_document"])
    date_c    = col(df, ["clearing_date"])
    for _, row in df.iterrows():
        cc_val   = str(row[cc_c])   if cc_c   and pd.notna(row.get(cc_c))   else ""
        fy_val   = str(row[fy_c])   if fy_c   and pd.notna(row.get(fy_c))   else ""
        acct_val = str(row[acct_c]) if acct_c and pd.notna(row.get(acct_c)) else str(_)
        date_val = str(row[date_c]) if date_c and pd.notna(row.get(date_c)) else ""
        nid = f"payment_{cc_val}_{fy_val}_{acct_val}"
        G.add_node(nid, **node_attrs(row, "Payment", date_val or acct_val))
        # Edge: JournalEntry → Payment (clearing_accounting_document links back)
        if clear_c and pd.notna(row.get(clear_c)):
            clear_val = str(row[clear_c])
            for key in [(cc_val, fy_val, clear_val)]:
                if key in journal_map:
                    safe_edge(G, journal_map[key], nid, "cleared_by")
    print(f"  Payments: {len(df)}")


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------

def export_graph_json(G: nx.DiGraph):
    nodes = []
    for nid, attrs in G.nodes(data=True):
        node_data = {"id": str(nid)}
        # Export ALL attributes — no truncation
        for k, v in attrs.items():
            if v is not None and v != "":
                node_data[str(k)] = str(v) if not isinstance(v, (int, float)) else v
        nodes.append(node_data)

    edges = []
    for u, v, attrs in G.edges(data=True):
        edges.append({
            "source": str(u),
            "target": str(v),
            "relation": str(attrs.get("relation", ""))
        })

    with open(GRAPH_JSON, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, ensure_ascii=False)

    print(f"\n  Exported {len(nodes)} nodes, {len(edges)} edges → {GRAPH_JSON}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Loading tables from DB...")
    conn = sqlite3.connect(DB_PATH)
    tables = load_tables(conn)
    conn.close()

    print("\nBuilding graph nodes...")
    G = nx.DiGraph()

    # Supporting entities first (referenced by core flow)
    customer_map = add_customers(G, tables)
    product_map  = add_products(G, tables)
    plant_map    = add_plants(G, tables)
    add_addresses(G, tables, customer_map)

    # Core O2C flow
    so_map       = add_sales_orders(G, tables, customer_map)
    si_map       = add_sales_order_items(G, tables, so_map, product_map)
    add_schedule_lines(G, tables, si_map)

    delivery_map = add_deliveries(G, tables, plant_map)
    add_delivery_items(G, tables, delivery_map, si_map)

    invoice_map  = add_invoices(G, tables, customer_map)
    add_invoice_items(G, tables, invoice_map, si_map)
    add_cancellations(G, tables, invoice_map)

    journal_map  = add_journal_entries(G, tables, invoice_map)
    add_payments(G, tables, journal_map)

    print("\n--- Final Stats ---")
    print(f"Total nodes : {G.number_of_nodes():,}")
    print(f"Total edges : {G.number_of_edges():,}")

    types = {}
    for _, d in G.nodes(data=True):
        t = d.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t:30s} {c:5d}")

    top = sorted(G.degree(), key=lambda x: -x[1])[:10]
    print("\nTop 10 most connected nodes:")
    for nid, deg in top:
        ntype = G.nodes[nid].get("type", "?")
        print(f"  [{ntype}] {nid}  →  degree {deg}")

    print("\nExporting graph.json...")
    export_graph_json(G)

    print("\nSaving graph.pkl...")
    with open(GRAPH_PKL, "wb") as f:
        pickle.dump(G, f)

    print("\nDone.")


if __name__ == "__main__":
    main()
