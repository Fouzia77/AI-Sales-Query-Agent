# AI Sales Query Agent — FastAPI, MCP-style SQLite tools, and Text-to-SQL

A containerized API that translates natural-language sales questions into read-only SQLite queries and returns rows plus chart-friendly data. It is designed to be easy to run locally and safe to evaluate without paid API credentials.

## Features

- **FastAPI** `POST /query` endpoint with a documented JSON contract.
- **MCP-style database boundary** in `mcp_server.py`: `list_tables()`, `describe_schema(table_name)`, and `execute_query(sql, params)`.
- **Read-only database access**: SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`; non-SELECT and multi-statement SQL is rejected.
- **Provider flexibility**: optionally uses Anthropic Claude or an Ollama endpoint; if neither is configured or a provider fails, deterministic offline SQL patterns cover the task's required questions and evaluator queries.
- **Docker Compose**, health check, Pytest coverage, and a five-question end-to-end evaluator.
- **Portable sample database** at `data/sales.db` with 500 customers and representative sales data. The assignment text refers to a supplied database, but the task attachment did not include a separate `sales.db`, so this project includes a compatible reproducible dataset.

## Architecture

```text
Client / Swagger UI
       |
       v
FastAPI POST /query  --->  SalesQueryAgent
                                 |
                       reads schema via MCP tools
                                 |
                    Claude / Ollama / offline planner
                                 |
                         generated SELECT SQL
                                 |
                                 v
                     MCPDatabaseServer.execute_query
                       (read-only SQLite boundary)
                                 |
                                 v
               { sql, results, chart_data: {labels, values} }
```

The MCP component is an **in-process implementation of the requested MCP pattern**, as specified in the assignment; it is not a separate network MCP server. The LLM does not receive database credentials or a direct connection. All database reads go through the narrow tool interface.

## Requirements

- Docker Desktop with Docker Compose v2, or Python 3.11+ for running outside Docker.
- On Windows, use PowerShell for Docker commands. Use Git Bash or WSL for `./evaluator.sh`.
- No API key is required for the included offline mode.

## Run with Docker (recommended)

Run these commands from the project root (`sales-query-agent`).

### 1. Check the database file exists

**PowerShell:**

```powershell
Test-Path .\data\sales.db
```

It should print `True`. Do not delete `data/sales.db`.

### 2. Create your local environment file (optional)

The app works without an API key. If you want Claude, copy the example file and add your key:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and set `ANTHROPIC_API_KEY=your_key_here`. Never commit `.env` or share your key. If you don't have a key, you can skip this step entirely; Compose supplies an empty key and offline mode works.

### 3. Build and start

```powershell
docker compose up --build -d
```

Wait for startup and check status:

```powershell
docker compose ps
docker compose logs --tail 100 api
```

The `api` service should become `healthy`. Verify the database is mounted:

```powershell
docker compose exec api python -c "import os; print(os.path.exists('/app/data/sales.db'))"
```

Expected output: `True`.

### 4. Open the API

- Swagger UI: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

Example request in PowerShell:

```powershell
$body = @{ question = 'What is the total number of customers?' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/query -ContentType 'application/json' -Body $body
```

Expected: a JSON object containing `sql`, `results`, and `chart_data`; the total customer count is **500**.

Test the category join query:

```powershell
$body = @{ question = "What is the total revenue from the 'Technology' category?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/query -ContentType 'application/json' -Body $body
```

### 5. Run automated tests

```powershell
docker compose exec api pytest -q
```

All tests should pass. If you change Python files, rebuild/recreate the container with `docker compose up --build -d` before testing.

### 6. Run the end-to-end evaluator

Open **Git Bash** in the project directory:

```bash
./evaluator.sh
```

It waits for the API, submits five sales questions, and exits non-zero if any response fails or has an empty `results` array. Expected final line: `5 / 5 queries succeeded.`

## Run without Docker (optional)

From the project root, create and activate a virtual environment, install dependencies, then start Uvicorn.

**PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:DATABASE_URL = 'sqlite:///./data/sales.db'
uvicorn main:app --host 127.0.0.1 --port 8000
```

In a second terminal, activate the same environment and run `pytest -q`. The evaluator script works in Git Bash if `curl` and Python are installed.

## API contract

### `POST /query`

Request:

```json
{"question": "What is the total number of customers?"}
```

Success response shape:

```json
{
  "sql": "SELECT COUNT(*) AS total_customers FROM customers",
  "results": [{"total_customers": 500}],
  "chart_data": {"labels": ["total_customers"], "values": [500.0]}
}
```

`chart_data.labels` contains category/label values when the query returns a label and a numeric column. `chart_data.values` contains the matching numeric values. A scalar aggregate is represented as one label/value pair.

Unanswerable questions return HTTP 400 with a JSON `detail` message. Malformed requests are validated by FastAPI. Unexpected database/provider errors do not expose credentials or raw exception contents to the client.

## Security notes

- SQLite connections use read-only URI mode and `PRAGMA query_only=ON`.
- Query execution only accepts a single `SELECT` statement; SQL comments, multiple statements, and known side-effecting keywords are checked.
- `execute_query` accepts a `params` argument and passes parameters separately to `sqlite3.execute`, avoiding string interpolation for bound values.
- Table descriptions only allow the four expected tables.
- LLM output is treated as untrusted and validated again at the database boundary.

Text-to-SQL is still a constrained analytics interface, not a substitute for authorization controls in a production system. For a real deployment, add authentication, rate limiting, query timeouts/row limits, structured SQL parsing, audit logs, and a separately deployed standards-compliant MCP server if required.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | No | Enables Claude SQL generation when set |
| `ANTHROPIC_MODEL` | No | Anthropic model name; defaults to `claude-3-5-haiku-latest` |
| `OLLAMA_BASE_URL` | No | Optional Ollama base URL, e.g. `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | No | Ollama model name; defaults to `llama3.2` |
| `DATABASE_URL` | No | Defaults to `sqlite:///./data/sales.db` |

## Useful commands

```powershell
# Inspect API logs
docker compose logs -f api

# Stop containers (keeps your database file)
docker compose down

# Rebuild after code/dependency changes
docker compose up --build -d

# Check database tables
docker compose exec api python -c "from mcp_server import MCPDatabaseServer; d=MCPDatabaseServer(); print(d.list_tables())"
```


