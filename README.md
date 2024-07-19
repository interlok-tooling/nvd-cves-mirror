# NVD API CVEs Cache

[![NVD API Cache](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml/badge.svg)](https://github.com/interlok-tooling/nvd-cves-mirror/actions/workflows/nvd-cache.yml)
![GitHub last commit (branch)](https://img.shields.io/github/last-commit/interlok-tooling/nvd-cves-mirror/nvd-cache?path=%2Fnvd_api_cache%2Fcache.properties&label=Last%20cache%20update)

Use https://github.com/jeremylong/Open-Vulnerability-Project vulnz.jar (same author as the gradle dependency check plugin) to cache data from [NVD API](https://services.nvd.nist.gov/rest/json/cves/2.0).
The data from the API is transfomed into data feed and added to [this project nvd-cache branch](https://github.com/interlok-tooling/nvd-cves-mirror/tree/nvd-cache).
A github action run every 8 hours to update the data from [NVD API](https://services.nvd.nist.gov/rest/json/cves/2.0) and requires the `NVD_API_KEY` secrets
Then it can be used by other projects using  gradle dependency check plugin by setting the `datafeedUrl` to `https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/`:

```
dependencyCheck  {
  ...
  nvd {
    apiKey = System.getenv("NVD_API_KEY")
    datafeedUrl="https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/"
  }
  ...
}
```
