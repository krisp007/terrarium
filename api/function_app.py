"""Read-only Azure Functions API for the terrarium cloud mirror."""

from __future__ import annotations

import json
import os
from typing import Any

import azure.functions as func
from azure.cosmos import CosmosClient


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _database() -> Any:
    endpoint = os.environ.get("COSMOS_URL")
    key = os.environ.get("COSMOS_KEY")
    database_name = os.environ.get("COSMOS_DATABASE", "db-terrarium")
    if not endpoint or not key:
        raise RuntimeError("COSMOS_URL and COSMOS_KEY are not configured")
    return CosmosClient(endpoint, key).get_database_client(database_name)


def _query(container_name: str, query: str, parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    container = _database().get_container_client(container_name)
    return list(
        container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        )
    )


def _json_response(payload: Any, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
    )


@app.route(route="history", methods=["GET"])
def history(request: func.HttpRequest) -> func.HttpResponse:
    """Return recent cloud history across sensor, alert, and status records."""
    try:
        limit = min(max(int(request.params.get("limit", "100")), 1), 500)
        documents: list[dict[str, Any]] = []
        query = "SELECT TOP @limit * FROM c ORDER BY c.timestamp DESC"
        parameters = [{"name": "@limit", "value": limit}]
        for container_name in ("sensor_readings", "alerts", "device_status"):
            documents.extend(_query(container_name, query, parameters))
        documents.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
        return _json_response(documents[:limit])
    except (ValueError, RuntimeError, Exception) as error:
        return _json_response({"error": "Cloud history unavailable", "detail": str(error)}, 503)


@app.route(route="status", methods=["GET"])
def status(request: func.HttpRequest) -> func.HttpResponse:
    """Return the latest cloud status document for the requested device."""
    try:
        device_id = request.params.get("deviceId", "terrarium-pi")
        query = (
            "SELECT TOP 1 * FROM c WHERE c.deviceId = @deviceId "
            "ORDER BY c.timestamp DESC"
        )
        documents = _query("device_status", query, [{"name": "@deviceId", "value": device_id}])
        return _json_response(documents[0] if documents else {"deviceId": device_id, "status": "unknown"})
    except (RuntimeError, Exception) as error:
        return _json_response({"error": "Cloud status unavailable", "detail": str(error)}, 503)