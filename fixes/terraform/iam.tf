# GA: scoped-bedrock-access and batch-for-offline-jobs. These policies replace the `bedrock:*` on `*` statement:
# after apply, the client deletes the "Bedrock" statement from the assistant-runtime inline policy.
data "aws_iam_policy_document" "runtime" {
  statement {
    sid     = "InvokeRouteProfiles"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = concat(
      [for route in local.interactive_routes : aws_bedrock_inference_profile.route[route].arn],
      [for route in local.interactive_routes : "arn:${local.partition}:bedrock:${local.region}:${local.account}:inference-profile/${var.routes[route]}"],
      # Cross-Region profiles route to the same foundation model in any Region of their geography.
      [for route in local.interactive_routes : "arn:${local.partition}:bedrock:*::foundation-model/${local.foundation_models[route]}"],
    )
  }

  statement {
    sid       = "ApplyGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.assistant.guardrail_arn]
  }

  statement {
    sid       = "RetrieveCatalog"
    actions   = ["bedrock:Retrieve"]
    resources = [aws_bedrockagent_knowledge_base.catalog.arn]
  }

  statement {
    sid       = "GuardrailKey"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.genai.arn]
  }
}

resource "aws_iam_role_policy" "runtime" {
  name   = "bedrock-scoped"
  role   = var.runtime_role_name
  policy = data.aws_iam_policy_document.runtime.json
}

data "aws_iam_policy_document" "enrich" {
  statement {
    sid     = "BatchJobs"
    actions = ["bedrock:CreateModelInvocationJob", "bedrock:GetModelInvocationJob", "bedrock:StopModelInvocationJob"]
    resources = [
      "arn:${local.partition}:bedrock:${local.region}:${local.account}:model-invocation-job/*",
      aws_bedrock_inference_profile.route["enrich"].arn,
      "arn:${local.partition}:bedrock:${local.region}:${local.account}:inference-profile/${var.routes["enrich"]}",
      "arn:${local.partition}:bedrock:*::foundation-model/${local.foundation_models["enrich"]}",
    ]
  }

  statement {
    sid       = "PassBatchRole"
    actions   = ["iam:PassRole"]
    resources = [var.batch_service_role_arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "enrich" {
  name   = "bedrock-batch"
  role   = var.enrich_role_name
  policy = data.aws_iam_policy_document.enrich.json
}
