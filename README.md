# NVD API CVEs Cache

[![NVD API Cache](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml/badge.svg)](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml)
![GitHub last commit (branch)](https://img.shields.io/github/last-commit/interlok-tooling/nvd-cves-mirror/nvd-cache?path=%2Fnvd_api_cache%2Fcache.properties&label=Last%20cache%20update)

This repository mirrors CVE cache data onto the `nvd-cache` branch for downstream Dependency Check consumers.

On `main`, the production mirror remains the existing `nvd-cache` feed.

On the `vulncheck` branch, the `NVD API Cache VulnCheck Canary` workflow builds an experimental Dependency Check-compatible feed from [VulnCheck NVD++](https://vulncheck.com/nvd2) and publishes it to the `nvd-cache-vulncheck` branch. That workflow requires the `VULNCHECK_API_TOKEN` repository secret.

Other projects can use the mirrored feed by setting `datafeedUrl` to `https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/`:

```
dependencyCheck  {
  ...
  nvd {
    datafeedUrl="https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/"
  }
  ...
}
```

For canary testing against the VulnCheck conversion branch, use:

```
https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache-vulncheck/nvd_api_cache/
```

The output branches contain a short attribution `README.md` to satisfy VulnCheck community usage requirements.
