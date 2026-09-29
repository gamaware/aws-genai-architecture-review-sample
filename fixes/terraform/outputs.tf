output "guardrail_id" {
  description = "Guardrail ID for the GUARDRAIL_ID environment variable of the ask and compare functions."
  value       = aws_bedrock_guardrail.assistant.guardrail_id
}

output "guardrail_version" {
  description = "Guardrail version for the GUARDRAIL_VERSION environment variable."
  value       = aws_bedrock_guardrail_version.assistant.version
}

output "inference_profile_arns" {
  description = "Application inference profile ARN per route, for the MODEL_ID environment variable."
  value       = { for route, profile in aws_bedrock_inference_profile.route : route => profile.arn }
}

output "knowledge_base_id" {
  description = "ID of the S3 Vectors knowledge base to ingest and compare before the switch."
  value       = aws_bedrockagent_knowledge_base.catalog.id
}

output "usage_plan_ids" {
  description = "Usage plan per channel."
  value       = { for channel, plan in aws_api_gateway_usage_plan.channel : channel => plan.id }
}
