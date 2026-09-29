# GA: vector-store-sizing. S3 Vectors replaces the OpenSearch Serverless collection. The collection is deleted only
# after re-ingestion and a golden-set retrieval comparison pass.
resource "aws_s3vectors_vector_bucket" "catalog" {
  vector_bucket_name = "${var.name_prefix}-vectors"

  encryption_configuration {
    sse_type    = "aws:kms"
    kms_key_arn = aws_kms_key.genai.arn
  }
}

resource "aws_s3vectors_index" "catalog" {
  index_name         = "product-catalog"
  vector_bucket_name = aws_s3vectors_vector_bucket.catalog.vector_bucket_name
  data_type          = "float32"
  dimension          = var.embedding_dimensions
  distance_metric    = "cosine"

  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}

data "aws_iam_role" "knowledge_base" {
  name = var.knowledge_base_role_name
}

data "aws_iam_policy_document" "knowledge_base_vectors" {
  statement {
    actions = [
      "s3vectors:PutVectors",
      "s3vectors:GetVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:QueryVectors",
      "s3vectors:GetIndex",
    ]
    resources = [aws_s3vectors_index.catalog.index_arn]
  }

  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.genai.arn]
  }
}

resource "aws_iam_role_policy" "knowledge_base_vectors" {
  name   = "s3-vectors"
  role   = data.aws_iam_role.knowledge_base.name
  policy = data.aws_iam_policy_document.knowledge_base_vectors.json
}

resource "aws_bedrockagent_knowledge_base" "catalog" {
  name     = "${var.name_prefix}-catalog"
  role_arn = data.aws_iam_role.knowledge_base.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:${local.partition}:bedrock:${local.region}::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.catalog.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.knowledge_base_vectors]
}
