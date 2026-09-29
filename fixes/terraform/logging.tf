# GA: invocation-logging and pii-in-logs. Invocation logs and the Lambda logs are KMS-encrypted and expire.
resource "aws_cloudwatch_log_group" "invocations" {
  name              = "/aws/bedrock/${var.name_prefix}/invocations"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.genai.arn
}

# The ask, compare and enrich log groups exist in the client's stack; `terraform import` brings them under this
# configuration so the key and retention apply to them too.
resource "aws_cloudwatch_log_group" "functions" {
  for_each = var.routes

  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.genai.arn
}

data "aws_iam_policy_document" "bedrock_logging_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:bedrock:${local.region}:${local.account}:*"]
    }
  }
}

resource "aws_iam_role" "bedrock_logging" {
  name               = "${var.name_prefix}-invocation-logging"
  assume_role_policy = data.aws_iam_policy_document.bedrock_logging_trust.json
}

data "aws_iam_policy_document" "bedrock_logging" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.invocations.arn}:log-stream:*"]
  }
}

resource "aws_iam_role_policy" "bedrock_logging" {
  name   = "write-invocation-logs"
  role   = aws_iam_role.bedrock_logging.id
  policy = data.aws_iam_policy_document.bedrock_logging.json
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  logging_config {
    text_data_delivery_enabled      = true
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    video_data_delivery_enabled     = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.invocations.name
      role_arn       = aws_iam_role.bedrock_logging.arn
    }
  }

  depends_on = [aws_iam_role_policy.bedrock_logging]
}
