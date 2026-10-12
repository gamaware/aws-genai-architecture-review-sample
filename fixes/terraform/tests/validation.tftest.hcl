mock_provider "aws" {
  source = "./tests/mocks"
}

run "rejects_single_region_model" {
  command = plan

  variables {
    routes = {
      ask     = "anthropic.claude-haiku-4-5-20251001-v1:0"
      compare = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
      enrich  = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }

  expect_failures = [var.routes]
}

run "rejects_short_log_retention" {
  command = plan

  variables {
    log_retention_days = 30
  }

  expect_failures = [var.log_retention_days]
}

run "rejects_burst_below_rate" {
  command = plan

  variables {
    channels = {
      web = { rate_limit = 40, burst_limit = 10, daily_quota = 40000 }
    }
  }

  expect_failures = [var.channels]
}

run "rejects_non_sns_alarm_topic" {
  command = plan

  variables {
    alarm_topic_arn = "not-an-arn"
  }

  expect_failures = [var.alarm_topic_arn]
}

run "rejects_incomplete_alarm_topic_arn" {
  command = plan

  variables {
    alarm_topic_arn = "arn:aws:sns:us-east-1:"
  }

  expect_failures = [var.alarm_topic_arn]
}

run "rejects_batch_role_path_without_trailing_slash" {
  command = plan

  variables {
    batch_service_role_path = "/service-role"
  }

  expect_failures = [var.batch_service_role_path]
}
