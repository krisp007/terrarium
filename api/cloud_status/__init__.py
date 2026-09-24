import azure.functions as func
import json


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        from shared import query

        device_id = req.params.get("deviceId", "terrarium-pi")
        sensor_documents = query(
            "sensor_readings",
            "SELECT TOP 1 * FROM c WHERE c.deviceId = @deviceId AND c.source = @source ORDER BY c.timestamp DESC",
            [
                {"name": "@deviceId", "value": device_id},
                {"name": "@source", "value": "esp32_sensors"},
            ],
        )
        command_documents = query(
            "device_status",
            "SELECT TOP 1 * FROM c WHERE c.deviceId = @deviceId AND c.topic = @topic ORDER BY c.timestamp DESC",
            [
                {"name": "@deviceId", "value": device_id},
                {"name": "@topic", "value": "moxa/cmd/output"},
            ],
        )
        sensors = sensor_documents[0].get("values", {}) if sensor_documents else {}
        raw_outputs = command_documents[0].get("values", {}) if command_documents else {}
        outputs = {
            f"DO@DO-{index:02d}": raw_outputs.get(f"do{index}", "OFF")
            for index in range(7)
        }
        payload = {
            "service": {"status": "cloud"},
            "mqtt": {"status": "cloud"},
            "esp32": {"status": "online" if sensors else "unknown", "sensors": sensors},
            "moxa": {"status": "cloud" if command_documents else "unknown", "outputs": outputs},
            "deviceId": device_id,
            "lastSeen": max(
                [document.get("timestamp", 0) for document in sensor_documents + command_documents],
                default=0,
            ),
        }
        return func.HttpResponse(json.dumps(payload), mimetype="application/json")
    except Exception as error:
        return func.HttpResponse(
            json.dumps({"error": "Cloud status unavailable", "detail": str(error)}),
            status_code=503,
            mimetype="application/json",
        )