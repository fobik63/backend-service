output "primary_ipv4" {
  description = "Primary origin IPv4 (set FAILOVER_PRIMARY_ORIGIN_IP / Cloudflare origin)"
  value       = hcloud_server.primary.ipv4_address
}

output "primary_ipv6" {
  description = "Primary origin IPv6"
  value       = hcloud_server.primary.ipv6_address
}

output "secondary_ipv4" {
  description = "Secondary / DR origin IPv4"
  value       = var.enable_secondary ? hcloud_server.secondary[0].ipv4_address : null
}

output "secondary_ipv6" {
  description = "Secondary / DR origin IPv6"
  value       = var.enable_secondary ? hcloud_server.secondary[0].ipv6_address : null
}

output "firewall_id" {
  description = "Hetzner firewall id attached to both origins"
  value       = hcloud_firewall.origin.id
}

output "ssh_key_id" {
  description = "Deploy SSH key id"
  value       = hcloud_ssh_key.deploy.id
}

output "one_click_hint" {
  description = "Next operator steps after terraform apply"
  value       = <<-EOT
    1. scp backend/.env deploy@${hcloud_server.primary.ipv4_address}:/opt/ai-card-master/.../backend/.env
    2. ssh deploy@${hcloud_server.primary.ipv4_address}
    3. bash deploy/one_click_deploy.sh --profile ${var.deploy_profile}
    4. Set FAILOVER_PRIMARY_ORIGIN_IP=${hcloud_server.primary.ipv4_address}
       FAILOVER_SECONDARY_ORIGIN_IP=${var.enable_secondary ? hcloud_server.secondary[0].ipv4_address : "N/A"}
    5. Optional: sudo bash deploy/harden_host.sh
  EOT
}
