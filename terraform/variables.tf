variable "short_name" {
  type        = string
  default     = "pnk"
  description = "The short name for the CloudFront distribution."
}

variable "bucket_name" {
  type        = string
  default     = "darkdell.pnk"
  description = "The name of the S3 bucket. Must be globally unique."
}

variable "domain_name" {
  type        = string
  default     = "pnk.darkdell.net"
  description = "The domain name for the CloudFront distribution."
}
