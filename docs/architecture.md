# Architecture
## Objectives

- **avoid legacy** technologies, build a clear **chain of trust**, support **encrypted storage** at rest
    - use **ssh keys** as root of trust for pulumi **stack secret** using **age**
    - store **secrets in the repository** using pulumi config secrets
    - per project **tls root-ca, server-certs**, rollout **m-tls** client certificates where possible
    - support **unattended boot and storage decryption** using tang/clevis/luks using https and a ca cert
- create **disposable/immutable-ish** infrastructure, aim for **structural isolation** and reusability
- treat **state as code**, favor **state reconcilation** tools
    - have the **complete encrypted state** in the **git repository** as **single source of truth**
- have a **big/full featured provision client** as the center of operation
    - target one **provision os** and a **container** for foreign distros and **continous integration** processes
    - facilitate a comfortable local **simulation environment** with **fast reconfiguration** turnaround
- **documentation** and **interactive notebooks** alongside code
    - help onboarding with **interactive tinkering** using **jupyter notebooks**
    - use mkdocs, **markdown** and **mermaid** to build a static **documentation website**
