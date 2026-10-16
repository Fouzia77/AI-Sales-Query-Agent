"""Text-to-SQL agent with optional Anthropic/Ollama providers and offline fallback."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from mcp_server import MCPDatabaseServer


class QueryPlanningError(ValueError):
    pass


class SalesQueryAgent:
    def __init__(self, database: MCPDatabaseServer) -> None:
        self.database = database

    def _schema_context(self) -> str:
        tables = self.database.list_tables()
        schema = [self.database.describe_schema(table) for table in tables]
        return json.dumps(schema, indent=2)

    def _llm_sql(self, question: str) -> str | None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key, timeout=20.0)
                response = client.messages.create(
                    model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                    max_tokens=500,
                    temperature=0,
                    system=(
                        "You translate sales analytics questions into exactly one SQLite SELECT query. "
                        "Return SQL only, no markdown. Use only the supplied schema. Never write or modify data. "
                        "For revenue, use orders.amount as order revenue unless product-category revenue is requested; "
                        "for product-category revenue, sum order_items.quantity * products.price and join orders, "
                        "order_items, and products when a category is specified."
                    ),
                    messages=[{"role": "user", "content": f"Schema:\n{self._schema_context()}\nQuestion: {question}\nSQL:"}],
                )
                text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
                return self._clean_sql(text)
            except Exception:
                # A provider/network error falls through to the deterministic planner.
                pass

        ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        if ollama_url:
            try:
                payload = json.dumps({
                    "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": "Return exactly one SQLite SELECT query and nothing else. Never modify data. Use only the supplied schema."},
                        {"role": "user", "content": f"Schema:\n{self._schema_context()}\nQuestion: {question}\nSQL:"},
                    ],
                    "options": {"temperature": 0},
                }).encode("utf-8")
                req = urllib.request.Request(ollama_url.rstrip("/") + "/api/chat", data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=25) as response:
                    result = json.loads(response.read().decode("utf-8"))
                return self._clean_sql(result.get("message", {}).get("content", ""))
            except Exception:
                pass
        return None

    @staticmethod
    def _clean_sql(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        match = re.search(r"(?is)\bSELECT\b.*", text)
        if not match:
            raise QueryPlanningError("The model did not return a SELECT query.")
        return match.group(0).strip()

    def _fallback_sql(self, question: str) -> str:
        q = re.sub(r"\s+", " ", question.lower()).strip(" ?.!\t\n")
        if any(word in q for word in ("weather", "temperature", "forecast outside", "capital of", "write a poem")):
            raise QueryPlanningError("This question is not answerable from the sales database. Ask about customers, orders, products, or revenue.")
        if re.search(r"\b(total number|how many|count|number of)\b.*\bcustomers?\b", q) or "customers are there" in q:
            return "SELECT COUNT(*) AS total_customers FROM customers"
        if "technology" in q and "revenue" in q and ("category" in q or "product" in q):
            # Category revenue is calculated from ordered quantity multiplied by product price.
            return ("SELECT ROUND(SUM(oi.quantity * p.price), 2) AS total_revenue "
                    "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
                    "JOIN products p ON p.id = oi.product_id WHERE p.category = 'Technology'")
        if "top 3 customers" in q and ("order count" in q or "orders" in q):
            return ("SELECT c.id, c.name, COUNT(o.id) AS order_count FROM customers c "
                    "JOIN orders o ON o.customer_id = c.id GROUP BY c.id, c.name "
                    "ORDER BY order_count DESC, c.id ASC LIMIT 3")
        if "average order value" in q and "region" in q:
            return ("SELECT c.region, ROUND(AVG(o.amount), 2) AS average_order_value "
                    "FROM orders o JOIN customers c ON c.id = o.customer_id "
                    "GROUP BY c.region ORDER BY c.region")
        if "monthly revenue" in q and "2024" in q:
            return ("SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(amount), 2) AS revenue "
                    "FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01' "
                    "GROUP BY strftime('%Y-%m', order_date) ORDER BY month")
        if "never been ordered" in q or "never ordered" in q or "not ordered" in q:
            return ("SELECT p.id, p.name, p.category FROM products p "
                    "LEFT JOIN order_items oi ON oi.product_id = p.id WHERE oi.product_id IS NULL ORDER BY p.id")
        if "spend" in q and "segment" in q:
            return ("SELECT c.segment, ROUND(SUM(o.amount), 2) AS total_spend "
                    "FROM customers c JOIN orders o ON o.customer_id = c.id "
                    "GROUP BY c.segment ORDER BY c.segment")
        if "revenue" in q and "region" in q:
            return ("SELECT c.region, ROUND(SUM(o.amount), 2) AS revenue FROM orders o "
                    "JOIN customers c ON c.id = o.customer_id GROUP BY c.region ORDER BY c.region")
        if "revenue" in q or "sales" in q:
            return "SELECT ROUND(SUM(amount), 2) AS total_revenue FROM orders"
        if "product" in q and ("list" in q or "all" in q or "show" in q):
            return "SELECT id, name, category, price FROM products ORDER BY id LIMIT 100"
        if "order" in q and ("list" in q or "all" in q or "show" in q):
            return "SELECT id, customer_id, amount, order_date FROM orders ORDER BY id LIMIT 100"
        if "customer" in q and ("list" in q or "all" in q or "show" in q):
            return "SELECT id, name, region, segment FROM customers ORDER BY id LIMIT 100"
        raise QueryPlanningError("I could not map this question to the sales schema. Try asking about customer counts, order counts, revenue, regions, product categories, or customer segments.")

    def answer(self, question: str) -> dict[str, Any]:
        if not question or not question.strip():
            raise QueryPlanningError("Question must not be empty.")
        # Reject clearly out-of-domain questions even when an LLM provider is configured.
        q_lower = question.lower()
        if any(word in q_lower for word in ("weather", "temperature", "forecast outside", "capital of", "write a poem")):
            raise QueryPlanningError("This question is not answerable from the sales database. Ask about customers, orders, products, or revenue.")
        # Always retrieve schema through the MCP boundary before planning SQL.
        self._schema_context()
        sql = self._llm_sql(question)
        if not sql:
            sql = self._fallback_sql(question)
        results = self.database.execute_query(sql)
        labels: list[str] = []
        values: list[float] = []
        if results:
            keys = list(results[0].keys())
            if len(keys) >= 2:
                label_key = keys[0]
                numeric_key = next((k for k in keys[1:] if isinstance(results[0].get(k), (int, float))), None)
                if numeric_key:
                    labels = [str(row.get(label_key, "")) for row in results]
                    values = [float(row[numeric_key]) if row.get(numeric_key) is not None else 0.0 for row in results]
            elif len(keys) == 1 and isinstance(results[0].get(keys[0]), (int, float)):
                labels = [keys[0]]
                values = [float(results[0][keys[0]])]
        return {"sql": sql, "results": results, "chart_data": {"labels": labels, "values": values}}
