variable "hcloud_token" {
  type        = string
  description = "Hetzner Cloud API token"
  sensitive   = true
}

variable "project_name" {
  type        = string
  description = "Name prefix for all resources"
  default     = "ai-card-master"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key for cloud-init / Hetzner SSH key"
}

variable "primary_location" {
  type        = string
  description = "Hetzner location for primary (fsn1=Falkenstein/DE, nbg1=Nuremberg, hel1=Helsinki)"
  default     = "fsn1"
}

variable "secondary_location" {
  type        = string
  description = "Hetzner location for secondary / DR (different DC from primary)"
  default     = "hel1"
}

variable "server_type" {
  type        = string
  description = "Hetzner server type (cpx31 ≈ 4 vCPU / 8 GB — enough for api+worker+pg+redis)"
  default     = "cpx31"
}

variable "image" {
  type        = string
  description = "OS image"
  default     = "ubuntu-24.04"
}

variable "enable_secondary" {
  type        = bool
  description = "Provision hot-standby secondary VM (plan §36 geo failover)"
  default     = true
}

variable "ssh_allow_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach SSH (VPN / jump hosts). Empty = no public SSH in firewall."
  default     = []
}

variable "enable_public_http" {
  type        = bool
  description = "Allow 80/443 from anywhere (only if NOT using Cloudflare Tunnel)"
  default     = false
}

variable "deploy_repo_url" {
  type        = string
  description = "Git clone URL used by cloud-init bootstrap"
  default     = "https://github.com/YOUR_ORG/AI-Card-Master.git"
}

variable "deploy_repo_ref" {
  type        = string
  description = "Git ref to checkout on first boot"
  default     = "main"
}

variable "deploy_profile" {
  type        = string
  description = "one_click_deploy profile: production | production_tunnel | disaster_recovery"
  default     = "production_tunnel"
}

variable "labels" {
  type        = map(string)
  description = "Extra Hetzner labels"
  default     = {}
}
