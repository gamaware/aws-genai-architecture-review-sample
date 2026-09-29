"""Nightly enrich job as one Bedrock batch inference job (closes the batch-for-offline-jobs finding).

The job writes one JSONL record per product to S3 and submits a model invocation job through the enrich route's
application inference profile. Batch inference bills tokens at the batch price, and the morning run reads the output
prefix. The Bedrock client is injected (boto3 `bedrock` in the job, a stub in the tests).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

# Bedrock batch inference rejects jobs below a minimum record count; smaller nights fall back to on-demand calls.
MIN_RECORDS = 100
ANTHROPIC_VERSION = "bedrock-2023-05-31"


class BedrockControl(Protocol):
    def create_model_invocation_job(self, **kwargs: Any) -> dict[str, Any]: ...


def records(products: list[dict[str, str]], system_prompt: str, max_tokens: int) -> str:
    lines = []
    for product in products:
        body = {
            "anthropic_version": ANTHROPIC_VERSION,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": [{"type": "text", "text": product["source_text"]}]}],
        }
        lines.append(json.dumps({"recordId": product["sku"], "modelInput": body}, sort_keys=True))
    return "\n".join(lines) + "\n"


def job_request(job_name: str, profile_arn: str, role_arn: str, input_uri: str, output_uri: str) -> dict[str, Any]:
    for uri in (input_uri, output_uri):
        if not uri.startswith("s3://"):
            raise ValueError(f"{uri} is not an S3 URI")
    return {
        "jobName": job_name,
        "modelId": profile_arn,
        "roleArn": role_arn,
        "inputDataConfig": {"s3InputDataConfig": {"s3Uri": input_uri, "s3InputFormat": "JSONL"}},
        "outputDataConfig": {"s3OutputDataConfig": {"s3Uri": output_uri}},
        "timeoutDurationInHours": 24,
        "tags": [{"key": "route", "value": "enrich"}],
    }


def submit(client: BedrockControl, record_count: int, request: dict[str, Any]) -> str | None:
    """Submit the job and return its ARN, or None when the night is too small for a batch job."""
    if record_count < MIN_RECORDS:
        return None
    return client.create_model_invocation_job(**request)["jobArn"]
