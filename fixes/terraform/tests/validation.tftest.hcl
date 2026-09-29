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
