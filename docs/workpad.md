# Workpad

Read `docs/development.md`.
Read the following required changes, considering which parts should be combined and which should be separate tasks and in what order they should be performed.

Required changes:

---

make system ipv6 capable, to finish postgres routing implementation without ipv6 issues on podman bridges that get a kernel default ipv6 unroutable link local address and some services (traefik) bind to it, and therefore cant connect to the ipv4 parts.

this happens if you enable public postgresql, where frontend and postgresql container get connected via two additional networks, to distinguish mtls and pwd

# Network IPV4 CIDR and IPV6 ULA-SUBNET of Internal, Podman and Nspawn Networks
NETWORK:
  INTERNAL_V4_CIDR: 10.87.240.1/24
  NSPAWN_V4_CIDR: 10.87.241.1/24
  PODMAN_V4_CIDR: 10.88.0.1/16
  PODMAN_POOL_V4_CIDR: 10.89.0.1/16
  # POOL is used from 0 to 99, 100 to 254 are free to use for PODMAN_STATIC_NETWORKS
  LIBVIRT_V4_CIDR: 192.168.122.1/24
  INTERNAL_V6_SUBNET: "871"
  NSPAWN_V6_SUBNET: "872"
  PODMAN_V6_SUBNET: "880"
  PODMAN_POOL_V6_SUBNET: "890"
  LIBVIRT_V6_SUBNET: "871"

---


- os/__init__.py: systemconfigupdate:

this component transfers the update service and main.sls using config.deployed=ssh_deploy and executes this with config_updated=ssh_execute.

sometimes, ssh_deploy finishes, but ssh_execute fails. i would like that the component realizes that, and will try ssh_deploy and ssh_execute next time again.

---

        # read ssh_authorized_keys from project_dir/authorized_keys and combine with provision key
        self.authorized_keys = ssh_provision_publickey.apply(
            lambda key: "".join(
                open(os.path.join(project_dir, "authorized_keys"), "r").readlines()
                + ["{}\n".format(key)]
            )
        )
