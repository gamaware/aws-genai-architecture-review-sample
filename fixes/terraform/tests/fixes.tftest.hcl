# Offline: the AWS provider is mocked, so these runs make no AWS calls and need no credentials.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "guardrail_covers_injection_and_pii" {
  command = apply

  assert {
    condition     = one([for f in aws_bedrock_guardrail.assistant.content_policy_config[0].filters_config : f.input_strength if f.type == "PROMPT_ATTACK"]) == "HIGH"
    error_message = "The guardrail must filter prompt attacks on input at HIGH strength."
  }

  assert {
    condition     = one([for p in aws_bedrock_guardrail.assistant.sensitive_information_policy_config[0].pii_entities_config : p.action if p.type == "PHONE"]) == "ANONYMIZE"
    error_message = "Phone numbers must be anonymized."
  }

  assert {
    condition     = aws_bedrock_guardrail.assistant.sensitive_information_policy_config[0].regexes_config[0].pattern == "HG-LOY-[0-9]{8}"
    error_message = "Loyalty card numbers must be matched by the regex policy."
  }

  assert {
    condition     = aws_bedrock_guardrail.assistant.kms_key_arn == aws_kms_key.genai.arn
    error_message = "The guardrail must be encrypted with the workload key."
  }
}

run "logs_are_encrypted_expire_and_capture_invocations" {
  command = apply

  assert {
    condition     = !aws_bedrock_model_invocation_logging_configuration.this.logging_config[0].text_data_delivery_enabled
    error_message = "Invocation logging must not deliver text data: Bedrock logs the original prompt, PII included, even when the guardrail anonymizes it."
  }

  assert {
    condition     = aws_bedrock_model_invocation_logging_configuration.this.logging_config[0].cloudwatch_config[0].log_group_name == aws_cloudwatch_log_group.invocations.name
    error_message = "Invocation logging must write to the encrypted invocations log group."
  }

  assert {
    condition     = alltrue([for g in concat([aws_cloudwatch_log_group.invocations], values(aws_cloudwatch_log_group.functions)) : g.retention_in_days >= 365 && g.kms_key_id == aws_kms_key.genai.arn])
    error_message = "Every log group needs the workload key and at least one year of retention."
  }

  assert {
    condition     = length(aws_cloudwatch_log_group.functions) == 3
    error_message = "The ask, compare and enrich log groups must be managed."
  }

  assert {
    condition     = aws_kms_key.genai.enable_key_rotation
    error_message = "Key rotation must be on."
  }
}

run "bedrock_access_is_scoped" {
  command = apply

  assert {
    condition     = alltrue(flatten([for s in data.aws_iam_policy_document.runtime.statement : [for a in s.actions : !strcontains(a, "*")]]))
    error_message = "The runtime policy must name each action; no wildcards."
  }

  assert {
    condition     = alltrue(flatten([for s in data.aws_iam_policy_document.runtime.statement : [for r in s.resources : r != "*"]]))
    error_message = "The runtime policy must not grant access on every resource."
  }

  assert {
    condition     = !contains(flatten([for s in data.aws_iam_policy_document.runtime.statement : s.actions]), "bedrock:CreateModelInvocationJob")
    error_message = "Batch job actions belong to the enrich role only."
  }

  assert {
    condition     = flatten([for s in data.aws_iam_policy_document.enrich.statement : [for c in s.condition : c.values] if s.sid == "PassBatchRole"]) == ["bedrock.amazonaws.com"]
    error_message = "The enrich role may pass the batch role to Bedrock only."
  }
}

run "one_tagged_profile_per_route" {
  command = apply

  assert {
    condition     = toset(keys(aws_bedrock_inference_profile.route)) == toset(["ask", "compare", "enrich"])
    error_message = "Each route needs its own application inference profile."
  }

  assert {
    condition     = alltrue([for route, p in aws_bedrock_inference_profile.route : p.tags["route"] == route && p.tags["cost-center"] == "digital-product"])
    error_message = "Profiles must carry the route and cost-center tags."
  }

  assert {
    condition     = strcontains(aws_bedrock_inference_profile.route["ask"].model_source[0].copy_from, "claude-haiku")
    error_message = "The ask route must move to Claude Haiku."
  }
}

run "every_channel_is_throttled" {
  command = apply

  assert {
    condition     = length(aws_api_gateway_usage_plan.channel) == 3 && alltrue([for p in aws_api_gateway_usage_plan.channel : p.quota_settings[0].period == "DAY"])
    error_message = "Each channel needs a usage plan with a daily quota."
  }

  assert {
    condition     = toset(keys(aws_api_gateway_method.assistant)) == toset(["ask", "compare"]) && alltrue([for m in aws_api_gateway_method.assistant : m.api_key_required])
    error_message = "The ask and compare methods must require an API key, or the usage plans do not apply to them."
  }

  assert {
    condition     = aws_api_gateway_method_settings.all.settings[0].throttling_rate_limit > 0
    error_message = "The stage needs a throttling ceiling."
  }
}

run "knowledge_base_on_s3_vectors" {
  command = apply

  assert {
    condition     = aws_bedrockagent_knowledge_base.catalog.storage_configuration[0].type == "S3_VECTORS"
    error_message = "The knowledge base must use S3 Vectors."
  }

  assert {
    condition     = aws_s3vectors_vector_bucket.catalog.encryption_configuration[0].sse_type == "aws:kms"
    error_message = "The vector bucket must use the workload key."
  }
}
