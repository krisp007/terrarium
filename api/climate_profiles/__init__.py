import json
import os
import time

import azure.functions as func


CONTAINER = os.environ.get("COSMOS_CLIMATE_CONTAINER", "climate_profiles")


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        from shared import query, response, upsert

        device_id = req.params.get("deviceId", "terrarium-pi")
        if req.method == "GET":
            documents = query(
                CONTAINER,
                "SELECT TOP 1 * FROM c WHERE c.deviceId = @deviceId ORDER BY c.updated_at DESC",
                [{"name": "@deviceId", "value": device_id}],
            )
            return response(documents[0] if documents else {"deviceId": device_id, "profiles": {}})

        if req.method == "PUT":
            payload = req.get_json()
            if not isinstance(payload, dict) or not isinstance(payload.get("profiles", {}), dict):
                return response({"error": "profiles must be an object"}, 400)
            document = {
                "id": f"{device_id}:climate_profiles",
                "deviceId": device_id,
                "profiles": payload["profiles"],
                "updated_at": time.time(),
                "source": "terrarium-ui",
            }
            return response(upsert(CONTAINER, document))

        return response({"error": "method not allowed"}, 405)
    except (ValueError, json.JSONDecodeError):
        return func.HttpResponse(json.dumps({"error": "invalid JSON"}), status_code=400, mimetype="application/json")
    except Exception as error:
        return func.HttpResponse(json.dumps({"error": "Climate profiles unavailable", "detail": str(error)}), status_code=503, mimetype="application/json")