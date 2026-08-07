locals {
  common_labels = merge(
    {
      project = var.project_name
      managed = "terraform"
      plan    = "iac-40"
    },
    var.labels,
  )

  cloud_init_primary = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key  = var.ssh_public_key
    deploy_repo_url = var.deploy_repo_url
    deploy_repo_ref = var.deploy_repo_ref
    deploy_profile  = var.deploy_profile
    role            = "primary"
  })

  cloud_init_secondary = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key  = var.ssh_public_key
    deploy_repo_url = var.deploy_repo_url
    deploy_repo_ref = var.deploy_repo_ref
    deploy_profile  = var.deploy_profile
    role            = "secondary"
  })
}

resource "hcloud_ssh_key" "deploy" {
  name       = "${var.project_name}-deploy"
  public_key = var.ssh_public_key
  labels     = local.common_labels
}

resource "hcloud_server" "primary" {
  name        = "${var.project_name}-primary"
  server_type = var.server_type
  image       = var.image
  location    = var.primary_location
  ssh_keys    = [hcloud_ssh_key.deploy.id]
  user_data   = local.cloud_init_primary
  labels = merge(local.common_labels, {
    role = "primary"
  })
  firewall_ids = [hcloud_firewall.origin.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}

resource "hcloud_server" "secondary" {
  count = var.enable_secondary ? 1 : 0

  name        = "${var.project_name}-secondary"
  server_type = var.server_type
  image       = var.image
  location    = var.secondary_location
  ssh_keys    = [hcloud_ssh_key.deploy.id]
  user_data   = local.cloud_init_secondary
  labels = merge(local.common_labels, {
    role = "secondary"
  })
  firewall_ids = [hcloud_firewall.origin.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}
