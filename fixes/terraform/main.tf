data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

locals {
  account   = data.aws_caller_identity.current.account_id
  partition = data.aws_partition.current.partition
  region    = data.aws_region.current.region

  interactive_routes = ["ask", "compare"]

  # Foundation model IDs behind each cross-Region profile (the profile ID minus its geography prefix).
  foundation_models = { for route, profile in var.routes : route => join(".", slice(split(".", profile), 1, length(split(".", profile)))) }
}
