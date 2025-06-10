# Development

- the root Makefile is used for basic functions
- `make help` to list functions
- the root README.md describes the examples/skeleton/Makefile usage, not the root Makefile usage
- make help output:
```
build-env            Build python environment
build-env-clean      Remove build environment artifacts
clean                Remove all artifacts
docs                 Build docs for local usage and open in browser
docs-clean           Remove all generated docs
docs-online-build    Build docs for http serve
docs-serve           Rebuild and serve docs with autoreload
provision-container  Build dependencies for provisioning using a container
provision-local      Build dependencies for provisioning using system apps
py-clean             Remove python related artifacts
sim__                Run "pulumi $(args)"
test-all-container   Run all tests using container build deps
test-all-local       Run all tests using local build deps
test-scripts         Run script Tests
test-sim             Run sim up Tests
test-sim-clean       Remove Application Artifacts
try-renovate         Run Renovate in dry-run mode
```