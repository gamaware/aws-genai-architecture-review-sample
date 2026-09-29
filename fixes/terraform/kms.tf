# One customer managed key for the guardrail, the log groups and the vector bucket of this workload.
data "aws_iam_policy_document" "key" {
  # checkov:skip=CKV_AWS_109:Key policy; "*" is scoped to the key it is attached to.
  # checkov:skip=CKV_AWS_111:Key policy; "*" is scoped to the key it is attached to.
  # checkov:skip=CKV_AWS_356:Key policy; "*" is scoped to the key it is attached to.
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogs"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${local.region}.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${local.partition}:logs:${local.region}:${local.account}:log-group:*"]
    }
  }
}

resource "aws_kms_key" "genai" {
  description             = "${var.name_prefix}: guardrail, logs and vectors"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.key.json
}

resource "aws_kms_alias" "genai" {
  name          = "alias/${var.name_prefix}"
  target_key_id = aws_kms_key.genai.key_id
}
