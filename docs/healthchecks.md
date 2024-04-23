# Health Checks


### Single Container

- Define in: `<instance>.container`
```ini
[Container]
HealthCmd=/usr/bin/command

HealthInterval=2m
HealthOnFailure=kill
HealthRetries=5

HealthStartPeriod=1m
HealthStartupCmd=command
HealthStartupInterval=1m
HealthStartupRetries=8
HealthStartupSuccess=2
HealthStartupTimeout=1m33s
HealthTimeout=20s
```

### Compose Container

- Define in: `compose.yml`
```yaml
services:
  backend:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 1m30s
      timeout: 10s
      retries: 3
      start_period: 40s
      start_interval: 5s

```
