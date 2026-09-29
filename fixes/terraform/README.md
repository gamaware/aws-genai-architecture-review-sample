# Terraform fixes

One change to the production account that closes the account-level findings of the review: a versioned guardrail with
PII anonymization, model invocation logging with metadata only (Bedrock logs the original prompt even when the guardrail
anonymizes it, so text data delivery stays off), a customer managed KMS key with encrypted, expiring log groups, one
application inference profile per route, scoped IAM policies for the runtime and enrich roles, per-channel API
throttling with an API key required on the ask and compare methods, and an S3 Vectors knowledge base to replace the
OpenSearch Serverless collection.

The configuration reads the client's existing role names, REST API ID and stage as variables. Before the first apply,
the client imports the three Lambda log groups (`terraform import 'aws_cloudwatch_log_group.functions["ask"]'
/aws/lambda/product-assistant-ask`, and the same for compare and enrich) and the two API methods (`terraform import
'aws_api_gateway_method.assistant["ask"]' abc123/a1b2c3/POST`, and the same for compare). After the apply, it deploys
the stage so the methods require an API key, gives each channel its key, and removes the `bedrock:*` statement from the
runtime role once the scoped policy is in place.

Tests run offline against a mocked provider: `terraform test` (`tests/fixes.tftest.hcl` asserts the controls each
finding needs; `tests/validation.tftest.hcl` checks the input rules).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| terraform | >= 1.11.0, < 2.0.0 |
| aws | ~> 6.66 |

## Providers

| Name | Version |
| ---- | ------- |
| aws | 6.66.0 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_api_gateway_api_key.channel](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_api_key) | resource |
| [aws_api_gateway_method.assistant](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_method) | resource |
| [aws_api_gateway_method_settings.all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_method_settings) | resource |
| [aws_api_gateway_request_validator.assistant](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_request_validator) | resource |
| [aws_api_gateway_usage_plan.channel](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_usage_plan) | resource |
| [aws_api_gateway_usage_plan_key.channel](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_usage_plan_key) | resource |
| [aws_bedrock_guardrail.assistant](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail) | resource |
| [aws_bedrock_guardrail_version.assistant](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail_version) | resource |
| [aws_bedrock_inference_profile.route](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_inference_profile) | resource |
| [aws_bedrock_model_invocation_logging_configuration.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_model_invocation_logging_configuration) | resource |
| [aws_bedrockagent_knowledge_base.catalog](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_knowledge_base) | resource |
| [aws_cloudwatch_log_group.functions](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.invocations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_metric_alarm.throttled](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_iam_role.bedrock_logging](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.bedrock_logging](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.enrich](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.knowledge_base_vectors](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.runtime](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_kms_alias.genai](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.genai](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_s3vectors_index.catalog](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_index) | resource |
| [aws_s3vectors_vector_bucket.catalog](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_vector_bucket) | resource |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_iam_policy_document.bedrock_logging](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.bedrock_logging_trust](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.enrich](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.key](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.knowledge_base_vectors](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.runtime](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_role.knowledge_base](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_role) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| alarm\_topic\_arn | SNS topic that receives throttling alarms. | `string` | `"arn:aws:sns:us-east-1:111122223333:product-assistant-alerts"` | no |
| api\_methods | Methods of the REST API that call the model, keyed by route; each must require an API key. | ```map(object({ resource_id = string http_method = string }))``` | ```{ "ask": { "http_method": "POST", "resource_id": "a1b2c3" }, "compare": { "http_method": "POST", "resource_id": "d4e5f6" } }``` | no |
| authorizer\_id | ID of the existing Cognito authorizer on the REST API. | `string` | `"cog123"` | no |
| batch\_service\_role\_arn | Service role Bedrock batch inference assumes to read and write the enrich job's S3 prefix. | `string` | `"arn:aws:iam::111122223333:role/product-assistant-batch"` | no |
| channels | Per-channel API quotas: steady rate (requests per second), burst and daily request quota. | ```map(object({ rate_limit = number burst_limit = number daily_quota = number }))``` | ```{ "kiosk": { "burst_limit": 10, "daily_quota": 3000, "rate_limit": 5 }, "mobile": { "burst_limit": 30, "daily_quota": 12000, "rate_limit": 15 }, "web": { "burst_limit": 80, "daily_quota": 40000, "rate_limit": 40 } }``` | no |
| cost\_center | Cost center tag on the application inference profiles. | `string` | `"digital-product"` | no |
| embedding\_dimensions | Dimensions of the Titan Text Embeddings V2 vectors in the S3 Vectors index. | `number` | `1024` | no |
| enrich\_role\_name | IAM role of the enrich job, split from the runtime role. | `string` | `"product-assistant-enrich"` | no |
| knowledge\_base\_role\_name | Existing IAM role the knowledge base assumes. | `string` | `"product-assistant-kb"` | no |
| log\_retention\_days | Retention of the Lambda and invocation log groups. | `number` | `365` | no |
| name\_prefix | Prefix for every resource this change creates. | `string` | `"product-assistant"` | no |
| region | Region of the product-assistant stack. | `string` | `"us-east-1"` | no |
| rest\_api\_id | ID of the existing product-assistant REST API. | `string` | `"abc123"` | no |
| routes | Model per route. Keys are route names; values are system-defined cross-Region inference profile IDs. | `map(string)` | ```{ "ask": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "compare": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "enrich": "us.anthropic.claude-sonnet-4-5-20250929-v1:0" }``` | no |
| runtime\_role\_name | Existing IAM role of the ask and compare functions. | `string` | `"product-assistant-lambda"` | no |
| stage\_burst\_limit | Stage-wide burst. | `number` | `120` | no |
| stage\_name | Stage of the REST API that serves production traffic. | `string` | `"prod"` | no |
| stage\_rate\_limit | Stage-wide steady request rate, the ceiling above every usage plan. | `number` | `60` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| guardrail\_id | Guardrail ID for the GUARDRAIL\_ID environment variable of the ask and compare functions. |
| guardrail\_version | Guardrail version for the GUARDRAIL\_VERSION environment variable. |
| inference\_profile\_arns | Application inference profile ARN per route, for the MODEL\_ID environment variable. |
| knowledge\_base\_id | ID of the S3 Vectors knowledge base to ingest and compare before the switch. |
| usage\_plan\_ids | Usage plan per channel. |
<!-- END_TF_DOCS -->
