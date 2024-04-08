## DNS-Resolver

DNS Resolving is done using `Unbound`

- available under `dns.internal` on `udp/53`, `tcp/53` and `DoT:tcp/853`
- default upstream is **split round robin DoT (DNS over TLS)**
    - over 2x dns.google, 2x dns-unfiltered.adguard.com, 2x cloudflare-dns.com

### Examples
#### forward custom zones to another dns server

```yaml
DNS:
  FORWARD:
    - name: lan
      addr: 127.0.0.1@5353
      tls: false
    - name: 30.9.10.in-addr.arpa
    - addr: 127.0.0.1@5353
      tls: false
```

#### custom zone entries and public dns overrides

```yaml
DNS:
  SRV: |
    # A Record
    local-data: 'somecomputer.local. A 192.168.1.1'

    # PTR Record
    local-data-ptr: '192.168.1.1 somecomputer.local.'

    # local zone '.whatever'
    local-zone: 'whatever.' static
    local-data: 'me.whatever. A 192.168.2.1'

    # additional access control
    access-control: 192.168.2.0/24 allow

    # override public dns entry
    local-data: 'checkonline.home-assistant.io. 300 IN A 1.2.3.4'

```

#### non tls custom upstream

```yaml
DNS:
  UPSTREAM:
    - 1.2.3.4@53
  UPSTREAM_TLS: false
```

#### custom unbound config, must start with [section]
```yaml
DNS:
  EXTRA: |
    [section-of-unbound.conf]
    # see https://unbound.docs.nlnetlabs.nl/en/latest/

```