data "aws_route53_zone" "darkdell" {
  name = "darkdell.net."
}

resource "aws_route53_record" "darkdell_pnk" {
  zone_id = data.aws_route53_zone.darkdell.id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.cloudfront_distribution.domain_name
    zone_id                = aws_cloudfront_distribution.cloudfront_distribution.hosted_zone_id
    evaluate_target_health = false
  }
}
