import json
import azure.functions as func


def main(req: func.HttpRequest):
    try:
        from shared import query

        limit = min(max(int(req.params.get("limit", "100")), 1), 500)
        documents = []
        for container_name in ("sensor_readings", "alerts", "device_status"):
            documents.extend(query(container_name, "SELECT * FROM c", []))
        documents.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
        return func.HttpResponse(
            json.dumps(documents[:limit], default=str),
            mimetype="application/json",
        )
    except Exception as error:
        return func.HttpResponse(
            json.dumps({"error": "Cloud history unavailable", "detail": str(error)}),
            status_code=503,
            mimetype="application/json",
        )