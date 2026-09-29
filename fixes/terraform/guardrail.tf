# GA: guardrail-every-route and pii-in-logs. One guardrail for both interactive routes, called by version.
resource "aws_bedrock_guardrail" "assistant" {
  name                      = var.name_prefix
  description               = "Prompt-attack, content, topic and PII policies for every interactive route."
  blocked_input_messaging   = "Sorry, I can only help with Harbor Goods products and orders."
  blocked_outputs_messaging = "Sorry, I can't answer that. Please contact customer service."
  kms_key_arn               = aws_kms_key.genai.arn

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "MEDIUM"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "competitor-pricing"
      type       = "DENY"
      definition = "Requests to state, match or compare prices of other retailers."
      examples   = ["Is this tent cheaper at another store?", "Will you match another shop's price?"]
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }

    regexes_config {
      name        = "loyalty-card"
      description = "Harbor Goods loyalty card numbers."
      pattern     = "HG-LOY-[0-9]{8}"
      action      = "ANONYMIZE"
    }
  }
}

resource "aws_bedrock_guardrail_version" "assistant" {
  guardrail_arn = aws_bedrock_guardrail.assistant.guardrail_arn
  description   = "Released with the GenAI review fixes."
}
