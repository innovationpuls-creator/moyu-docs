from __future__ import annotations

from api.main import create_app


def test_task_retry_requires_uuid_idempotency_header() -> None:
    operation = create_app(debug=True).openapi()["paths"]["/v1/tasks/{task_id}/retry"][
        "post"
    ]
    header = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )

    assert header["in"] == "header"
    assert header["required"] is True
    assert header["schema"]["format"] == "uuid"
