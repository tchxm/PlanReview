terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "5.99.0"
    }
  }
}
provider "aws" {
  region = "ap-south-1"
  access_key = "test"
  secret_key = "test"
  skip_credentials_validation = true
  skip_requesting_account_id = true
  skip_metadata_api_check = true
}
resource "aws_lambda_function" "dev_api" {
  function_name = "dev-api"
  role = "arn:aws:iam::123456789012:role/demo"
  filename = "lambda.zip"
  handler = "index.handler"
  runtime = "python3.12"
  memory_size = 1024
  tags = { Environment = "dev" }
}
resource "aws_security_group" "api" {
  name = "dev-api"
  description = "Demo security group"
  vpc_id = "vpc-12345678"
  ingress = [{from_port=443,to_port=443,protocol="tcp",cidr_blocks=["10.0.0.0/8"],ipv6_cidr_blocks=[],prefix_list_ids=[],security_groups=[],self=false,description="Internal HTTPS"}]
  egress = []
  tags = { Environment = "dev" }
}
resource "aws_s3_bucket" "assets" {
  bucket = "planreview-demo-assets"
  tags = { Environment = "dev" }
}
resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id
  block_public_acls = true
  block_public_policy = true
  ignore_public_acls = true
  restrict_public_buckets = true
}
