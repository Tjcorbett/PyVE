GUI for proxmoxer/ProxmoxAPI written in Python


Change this info to connect to your Proxmox host:


# Configuration (use environment variables for security)
PROXMOX_HOST = os.getenv('PROXMOX_HOST', 'your_proxmox_ip')
PROXMOX_PORT = int(os.getenv('PROXMOX_PORT', 8006))
PROXMOX_USER = os.getenv('PROXMOX_USER', 'your_user') #Example User: root@pam
PROXMOX_PASSWORD = os.getenv('PROXMOX_PASSWORD', 'your_password')
PROXMOX_NODE = os.getenv('PROXMOX_NODE', 'pve')
VERIFY_SSL = os.getenv('PROXMOX_VERIFY_SSL', 'False').lower() == 'true'
