# Origin firewall: deny public Postgres/Redis/admin; SSH only from allowlist;
# HTTP(S) optional (prefer Cloudflare Tunnel — plan §37).

resource "hcloud_firewall" "origin" {
  name = "${var.project_name}-origin"
  labels = local.common_labels

  # SSH — only from operator / VPN CIDRs (empty list = no public SSH rule)
  dynamic "rule" {
    for_each = var.ssh_allow_cidrs
    content {
      direction   = "in"
      protocol    = "tcp"
      port        = "22"
      source_ips  = [rule.value]
      description = "SSH allowlist"
    }
  }

  # Optional public HTTP/S when tunnel is not used (Cloudflare orange-cloud + harden_host.sh)
  dynamic "rule" {
    for_each = var.enable_public_http ? [1] : []
    content {
      direction   = "in"
      protocol    = "tcp"
      port        = "80"
      source_ips  = ["0.0.0.0/0", "::/0"]
      description = "HTTP (prefer Cloudflare Tunnel instead)"
    }
  }

  dynamic "rule" {
    for_each = var.enable_public_http ? [1] : []
    content {
      direction   = "in"
      protocol    = "tcp"
      port        = "443"
      source_ips  = ["0.0.0.0/0", "::/0"]
      description = "HTTPS (prefer Cloudflare Tunnel instead)"
    }
  }

  # ICMP for basic reachability / failover probes
  rule {
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "ICMP"
  }
}
