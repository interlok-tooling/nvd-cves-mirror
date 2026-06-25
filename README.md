# NVD API CVEs Cache

[![NVD API Cache](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml/badge.svg)](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml)
![GitHub last commit (branch)](https://img.shields.io/github/last-commit/interlok-tooling/nvd-cves-mirror/nvd-cache?path=%2Fnvd_api_cache%2Fcache.properties&label=Last%20cache%20update)

This repository mirrors CVE cache data onto the `nvd-cache` branch for downstream Dependency Check consumers.

The cache is refreshed every 8 hours by GitHub Actions using [VulnCheck NVD++](https://vulncheck.com/nvd2), a free community service provided by VulnCheck Inc. The workflow downloads the published NVD 2.0 backup files directly into `nvd_api_cache` and requires the `VULNCHECK_API_TOKEN` repository secret.

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

The `nvd-cache` branch also contains a short attribution `README.md` to satisfy VulnCheck community usage requirements.
