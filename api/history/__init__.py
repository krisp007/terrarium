from __future__ import annotations

from typing import Any

import azure.functions as func

from shared import query, response


def main(req: func.HttpRequest) -> Any:
    try:
        limit = min(max(int(req.params.get("limit", "100")), 1), 500)
        statement = "SELECT TOP @limit * FROM c ORDER BY c.timestamp DESC"
        parameters = [{"name": "@limit", "value": limit}]
        documents: list[dict[str, Any]] = []
        for container_name in ("sensor_readings", "alerts", "device_status"):
            documents.extend(query(container_name, statement, parameters))
        documents.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
        return response(documents[:limit])
    except Exception as error:
        return response({"error": "Cloud history unavailable", "detail": str(error)}, 503)