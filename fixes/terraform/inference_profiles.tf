# GA: application-inference-profiles and right-sized-model. One tagged profile per route, so usage and cost show
# per route in Cost Explorer and CloudWatch, and a model change is a one-line change to var.routes.
resource "aws_bedrock_inference_profile" "route" {
  for_each = var.routes

  name        = "${var.name_prefix}-${each.key}"
  description = "Route ${each.key} of ${var.name_prefix}"

  model_source {
    copy_from = "arn:${local.partition}:bedrock:${local.region}:${local.account}:inference-profile/${each.value}"
  }

  tags = {
    route       = each.key
    cost-center = var.cost_center
  }
}
