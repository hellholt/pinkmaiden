locals {
  lambdas = {
    "image_api" = {
      layer_dir   = "../lambda_layer/image_api"
      lambda_file = "../lambda/image_api/lambda.py"
    },
    "image_thumbnail" = {
      layer_dir   = "../lambda_layer/image_thumbnail"
      lambda_file = "../lambda/image_thumbnail/lambda.py"
    }
  }
}

data "aws_iam_policy_document" "lambda_assume_role_policy_document" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::665449637458:user/nathan"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_policy" "s3_lambda_policy" {
  name        = "pinkmaiden_s3_lambda_policy"
  description = "Policy for Pinkmaiden Lambdas to access S3"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:PutLogEvents",
          "logs:CreateLogGroup",
          "logs:CreateLogStream"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Action = [
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:PutObject",
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.bucket.arn}/*",
      },
      {
        Action = [
          "s3:ListBucket",
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.bucket.arn}",
      }
    ]
  })
}

resource "aws_iam_role" "s3_lambda_role" {
  name               = "pinkmaiden_s3_lambda_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role_policy_document.json
  inline_policy {
    name   = "pinkmaiden_s3_lambda_policy"
    policy = aws_iam_policy.s3_lambda_policy.policy
  }
}

data "archive_file" "lambda_layer_zip" {
  for_each    = local.lambdas
  type        = "zip"
  source_dir  = each.value.layer_dir
  output_path = "/tmp/lambda/${each.key}/dist/${each.key}_lambda_layer.zip"
}

data "archive_file" "lambda_zip" {
  for_each    = local.lambdas
  type        = "zip"
  source_file = each.value.lambda_file
  output_path = "/tmp/lambda/${each.key}/dist/${each.key}_lambda.zip"
}

resource "aws_lambda_layer_version" "lambda_layer" {
  for_each            = local.lambdas
  filename            = data.archive_file.lambda_layer_zip[each.key].output_path
  layer_name          = "${each.key}_lambda_layer"
  compatible_runtimes = ["python3.9"]
  source_code_hash    = data.archive_file.lambda_layer_zip[each.key].output_base64sha256
}

resource "aws_lambda_function" "lambda_function" {
  for_each         = local.lambdas
  filename         = data.archive_file.lambda_zip[each.key].output_path
  function_name    = "${each.key}_lambda"
  role             = aws_iam_role.s3_lambda_role.arn
  handler          = "lambda.handler"
  source_code_hash = data.archive_file.lambda_zip[each.key].output_base64sha256
  runtime          = "python3.9"
  memory_size      = 128
  timeout          = 30
  layers           = [aws_lambda_layer_version.lambda_layer[each.key].arn]
  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.bucket.id,
      DOMAIN_NAME = var.domain_name,
    }
  }
}

resource "aws_lambda_permission" "allow_s3_image_thumbnail_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lambda_function["image_thumbnail"].function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.bucket.arn
}

resource "aws_s3_bucket_notification" "upload_notification" {
  bucket = aws_s3_bucket.bucket.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.lambda_function["image_thumbnail"].arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }
  depends_on = [
    aws_lambda_permission.allow_s3_image_thumbnail_lambda,
  ]
}
