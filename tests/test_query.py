from fastapi.testclient import TestClient

from main import app, _database
from mcp_server import MCPDatabaseServer

client = TestClient(app)


def test_total_customers_response_shape_and_value():
    response = client.post("/query", json={"question": "What is the total number of customers?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["sql"], str) and body["sql"].lstrip().upper().startswith("SELECT")
    assert isinstance(body["results"], list)
    assert body["results"][0]["total_customers"] == 500
    assert isinstance(body["chart_data"]["labels"], list)
    assert isinstance(body["chart_data"]["values"], list)


def test_category_revenue_query_works():
    response = client.post("/query", json={"question": "What is the total revenue from the 'Technology' category?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["total_revenue"] > 0
    assert "order_items" in body["sql"] and "products" in body["sql"] and "orders" in body["sql"]


def test_unanswerable_question_returns_400():
    response = client.post("/query", json={"question": "What is the weather like today?"})
    assert response.status_code == 400
    assert "detail" in response.json()


def test_non_select_statements_are_rejected():
    for sql in ["DROP TABLE customers;", "UPDATE customers SET name='x'", "SELECT 1; DROP TABLE customers;"]:
        try:
            _database.execute_query(sql)
        except (PermissionError, ValueError):
            pass
        else:
            raise AssertionError(f"Unsafe SQL was accepted: {sql}")


def test_evaluator_queries_return_rows():
    questions = [
        "Top 3 customers by order count",
        "Average order value by region",
        "Monthly revenue for 2024",
        "Products that have never been ordered",
        "Total spend by customer segment",
    ]
    for question in questions:
        response = client.post("/query", json={"question": question})
        assert response.status_code == 200, f"{question}: {response.text}"
        assert response.json()["results"], f"No results for: {question}"
