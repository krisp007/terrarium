"""Shared Cosmos DB helpers for the Azure Functions endpoints."""

from __future__ import annotations

import json
import os
from typing import Any

from azure.cosmos import CosmosClient


def database() -> Any:
    endpoint = os.environ.get("COSMOS_URL")
    key = os.environ.get("COSMOS_KEY")
    if not endpoint or not key:
        raise RuntimeError("COSMOS_URL and COSMOS_KEY are not configured")
    return CosmosClient(endpoint, key).get_database_client(
        os.environ.get("COSMOS_DATABASE", "db-terrarium")
    )


def query(container_name: str, statement: str, parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    container = database().get_container_client(container_name)
    return list(
        container.query_items(
            query=statement,
            parameters=parameters,
            enable_cross_partition_query=True,
        )
    )


def upsert(container_name: str, document: dict[str, Any]) -> dict[str, Any]:
    """Upsert one document into a Cosmos container using its configured id."""
    container = database().get_container_client(container_name)
    return dict(container.upsert_item(document))


def response(payload: Any, status_code: int = 200) -> Any:
    import azure.functions as func

    return func.HttpResponse(
        body=json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
    )