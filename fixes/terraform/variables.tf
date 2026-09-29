variable "region" {
  description = "Region of the product-assistant stack."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for every resource this change creates."
  type        = string
  default     = "product-assistant"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name_prefix))
    error_message = "Use 3 to 31 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "cost_center" {
  description = "Cost center tag on the application inference profiles."
  type        = string
  default     = "digital-product"
}

variable "runtime_role_name" {
  description = "Existing IAM role of the ask and compare functions."
  type        = string
  default     = "product-assistant-lambda"
}

variable "enrich_role_name" {
  description = "IAM role of the enrich job, split from the runtime role."
  type        = string
  default     = "product-assistant-enrich"
}

variable "knowledge_base_role_name" {
  description = "Existing IAM role the knowledge base assumes."
  type        = string
  default     = "product-assistant-kb"
}

variable "batch_service_role_arn" {
  description = "Service role Bedrock batch inference assumes to read and write the enrich job's S3 prefix."
  type        = string
  default     = "arn:aws:iam::111122223333:role/product-assistant-batch"

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/", var.batch_service_role_arn))
    error_message = "Must be an IAM role ARN."
  }
}

variable "rest_api_id" {
  description = "ID of the existing product-assistant REST API."
  type        = string
  default     = "abc123"
}

variable "authorizer_id" {
  description = "ID of the existing Cognito authorizer on the REST API."
  type        = string
  default     = "cog123"
}

variable "api_methods" {
  description = "Methods of the REST API that call the model, keyed by route; each must require an API key."
  type = map(object({
    resource_id = string
    http_method = string
  }))
  default = {
    ask     = { resource_id = "a1b2c3", http_method = "POST" }
    compare = { resource_id = "d4e5f6", http_method = "POST" }
  }
}

variable "stage_name" {
  description = "Stage of the REST API that serves production traffic."
  type        = string
  default     = "prod"
}

variable "alarm_topic_arn" {
  description = "SNS topic that receives throttling alarms."
  type        = string
  default     = "arn:aws:sns:us-east-1:111122223333:product-assistant-alerts"
}

variable "routes" {
  description = "Model per route. Keys are route names; values are system-defined cross-Region inference profile IDs."
  type        = map(string)
  default = {
    ask     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    compare = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    enrich  = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
  }

  validation {
    condition     = alltrue([for id in values(var.routes) : can(regex("^(us|eu|apac|global)\\.", id))])
    error_message = "Every route must use a cross-Region inference profile ID."
  }
}

variable "channels" {
  description = "Per-channel API quotas: steady rate (requests per second), burst and daily request quota."
  type = map(object({
    rate_limit  = number
    burst_limit = number
    daily_quota = number
  }))
  default = {
    web    = { rate_limit = 40, burst_limit = 80, daily_quota = 40000 }
    mobile = { rate_limit = 15, burst_limit = 30, daily_quota = 12000 }
    kiosk  = { rate_limit = 5, burst_limit = 10, daily_quota = 3000 }
  }

  validation {
    condition     = alltrue([for c in values(var.channels) : c.rate_limit > 0 && c.burst_limit >= c.rate_limit && c.daily_quota > 0])
    error_message = "Each channel needs a positive rate, a burst at least equal to the rate, and a positive quota."
  }
}

variable "stage_rate_limit" {
  description = "Stage-wide steady request rate, the ceiling above every usage plan."
  type        = number
  default     = 60
}

variable "stage_burst_limit" {
  description = "Stage-wide burst."
  type        = number
  default     = 120
}

variable "log_retention_days" {
  description = "Retention of the Lambda and invocation log groups."
  type        = number
  default     = 365

  validation {
    condition     = var.log_retention_days >= 365
    error_message = "Keep invocation and application logs for at least one year."
  }
}

variable "embedding_dimensions" {
  description = "Dimensions of the Titan Text Embeddings V2 vectors in the S3 Vectors index."
  type        = number
  default     = 1024
}
