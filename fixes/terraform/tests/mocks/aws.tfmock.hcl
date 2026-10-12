# Shared mock values: the attributes the configuration parses or validates need realistic shapes.
mock_data "aws_caller_identity" {
  defaults = {
    account_id = "YOUR_AWS_ACCOUNT_ID"
  }
}

mock_data "aws_partition" {
  defaults = {
    partition = "aws"
  }
}

mock_data "aws_region" {
  defaults = {
    region = "us-east-1"
  }
}

mock_data "aws_iam_policy_document" {
  defaults = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
  }
}

mock_data "aws_iam_role" {
  defaults = {
    arn = "arn:aws:iam::YOUR_AWS_ACCOUNT_ID:role/product-assistant-kb"
  }
}

mock_resource "aws_kms_key" {
  defaults = {
    arn = "arn:aws:kms:us-east-1:YOUR_AWS_ACCOUNT_ID:key/1234abcd-12ab-34cd-56ef-1234567890ab"
  }
}

mock_resource "aws_bedrock_guardrail" {
  defaults = {
    guardrail_arn = "arn:aws:bedrock:us-east-1:YOUR_AWS_ACCOUNT_ID:guardrail/example1234"
    guardrail_id  = "example1234"
  }
}

mock_resource "aws_iam_role" {
  defaults = {
    arn = "arn:aws:iam::YOUR_AWS_ACCOUNT_ID:role/product-assistant-invocation-logging"
  }
}

mock_resource "aws_s3vectors_index" {
  defaults = {
    index_arn = "arn:aws:s3vectors:us-east-1:YOUR_AWS_ACCOUNT_ID:bucket/product-assistant-vectors/index/product-catalog"
  }
}

mock_resource "aws_bedrock_inference_profile" {
  defaults = {
    arn = "arn:aws:bedrock:us-east-1:YOUR_AWS_ACCOUNT_ID:application-inference-profile/example1234"
  }
}

mock_resource "aws_bedrockagent_knowledge_base" {
  defaults = {
    arn = "arn:aws:bedrock:us-east-1:YOUR_AWS_ACCOUNT_ID:knowledge-base/EXAMPLE123"
  }
}
