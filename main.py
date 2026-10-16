"""FastAPI entry point for the AI Sales Query Agent."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import QueryPlanningError, SalesQueryAgent
from mcp_server import MCPDatabaseServer

app = FastAPI(
    title="AI Sales Query Agent",
    description="Ask sales questions in natural language; receive read-only SQL results and chart data.",
    version="1.0.0",
)
_database = MCPDatabaseServer()
_agent = SalesQueryAgent(_database)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="A question about the sales database")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": "connected" if _database.list_tables() else "empty"}


@app.post("/query")
def query(request: QueryRequest) -> dict:
    try:
        return _agent.answer(request.question)
    except QueryPlanningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Return a useful but non-sensitive error; details remain in container logs.
        raise HTTPException(status_code=500, detail=f"Query execution failed: {type(exc).__name__}") from exc
