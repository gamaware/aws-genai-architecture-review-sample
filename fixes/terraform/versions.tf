terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      app        = var.name_prefix
      managed-by = "terraform"
      change     = "genai-review-fixes"
    }
  }
}
