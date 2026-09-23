from __future__ import annotations

from typing import Any

import azure.functions as func

from shared import query, response


def main(req: func.HttpRequest) -> Any:
    try:
        device_id = req.params.get("deviceId", "terrarium-pi")
        statement = (
            "SELECT TOP 1 * FROM c WHERE c.deviceId = @deviceId "
            "ORDER BY c.timestamp DESC"
        )
        documents = query("device_status", statement, [{"name": "@deviceId", "value": device_id}])
        return response(documents[0] if documents else {"deviceId": device_id, "status": "unknown"})
    except Exception as error:
        return response({"error": "Cloud status unavailable", "detail": str(error)}, 503)