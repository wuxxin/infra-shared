## DNS-Resolver

DNS Resolving is done using `Unbound`
- available under `dns.internal` on udp/53, tcp/53 and DoT:tcp/853
- the default upstream is split round robin DoT (DNS over TLS) over
    - 2x dns.google, 2x dns-unfiltered.adguard.com, 2x cloudflare-dns.com

### Environment

```yaml
DNS_RESOLVER: true      # true/false
DNS_VERBOSITY: "1"      # Integer String: "0-5"
DNS_UPSTREAM_TLS: true  # true/false
DNS_UPSTREAM:           # list, defaults: None
# if not defined upstream is taken from dnsresolver_ext.conf
# custom upstream forwarder list syntax:
# - 1.2.3.4@567#dns.domain
DNS_FORWARD:            # list, defaults: None
# custom forwarder list syntax:
# - name: zone,
#   addr: addr
#   tls: true
DNS_EXT: |
  # custom text appended to dnsresolver_ext.conf
  # Use to start new clauses
DNS_SRV: |
  # custom text appended to dnsresolver_srv.conf
  # placed _inside_ the server clause

```


#### forward custom zones to another dns server

```yaml
DNS_FORWARD:
  - name: lan
    addr: 127.0.0.1@5353
    tls: false
  - name: 30.9.10.in-addr.arpa
  - addr: 127.0.0.1@5353
    tls: false
```

#### custom zone entries and public dns overrides

```yaml
DNS_SRV: |
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
DNS_UPSTREAM:
  - 1.2.3.4@53
DNS_UPSTREAM_TLS: false
```
