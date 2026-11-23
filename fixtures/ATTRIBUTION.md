# Attribution

Every fixture in this directory contains excerpts of source code taken from a public repository. The code remains the work of its authors and stays under that repository's license, which is listed below. These excerpts are reproduced to evaluate code review tools, not as a copy of the projects.

A fixture is a **reversed** change: the diff is a real commit or pull request run backwards, and explanatory comment lines that the original change deleted were dropped from its old side, as the `provenance.construction` field of each fixture says. The code is otherwise as published. See [README.md](README.md).

## Fixtures

| Fixture | Repository | License | Source |
|---|---|---|---|
| `cobra-stderr-routing` | [spf13/cobra](https://github.com/spf13/cobra) | Apache-2.0 | [PR #894 (merge commit 40d34bca1bffe2f5e84b18d7fd94d5b3c02275](https://github.com/spf13/cobra/pull/894) |
| `eslint-logical-operator-crash` | [eslint/eslint](https://github.com/eslint/eslint) | MIT | [PR #10476 (merge commit f93d6ff53acd19b39dbc1c7d0e5ffa7d71c8](https://github.com/eslint/eslint/pull/10476) |
| `etherpad-static-path-traversal` | [ether/etherpad](https://github.com/ether/etherpad) | Apache-2.0 | [9c8d16d50e2fdfd9693ab35c43280410cb4db2fc](https://github.com/ether/etherpad/commit/9c8d16d50e2fdfd9693ab35c43280410cb4db2fc) |
| `helm-alias-shared-dependencies` | [helm/helm](https://github.com/helm/helm) | Apache-2.0 | [PR #9175 (merge commit a911aa211248899a8722159f8422a96a8222a](https://github.com/helm/helm/pull/9175) |
| `ipython-right-arrow-suggestion` | [ipython/ipython](https://github.com/ipython/ipython) | BSD-3-Clause | [PR #14052 (merge commit 78fcf82238fb1ca7f84ed25fde0034610e67](https://github.com/ipython/ipython/pull/14052) |
| `jackson-typeid-cache-unbounded` | [FasterXML/jackson-databind](https://github.com/FasterXML/jackson-databind) | Apache-2.0 | [2870d1d6dc1b7e1c07ee11dd5b04ab71cddbb577](https://github.com/FasterXML/jackson-databind/commit/2870d1d6dc1b7e1c07ee11dd5b04ab71cddbb577) |
| `kubeflow-shared-pipeline-rbac-fixed` | [kubeflow/pipelines](https://github.com/kubeflow/pipelines) | Apache-2.0 | [186dd1f3b0403af841c9b4ea7ab94f405339ef6c](https://github.com/kubeflow/pipelines/commit/186dd1f3b0403af841c9b4ea7ab94f405339ef6c) |
| `kubeflow-shared-pipeline-rbac` | [kubeflow/pipelines](https://github.com/kubeflow/pipelines) | Apache-2.0 | [186dd1f3b0403af841c9b4ea7ab94f405339ef6c](https://github.com/kubeflow/pipelines/commit/186dd1f3b0403af841c9b4ea7ab94f405339ef6c) |
| `mem0-databricks-sql-injection` | [mem0ai/mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | [a2ffca32660537b7b304305f36774ae2a13452cb](https://github.com/mem0ai/mem0/commit/a2ffca32660537b7b304305f36774ae2a13452cb) |
| `netfoil-ttl-not-decremented` | [tinfoil-factory/netfoil](https://github.com/tinfoil-factory/netfoil) | Apache-2.0 | [ea42977900c864b7b1c42f26c5870c86008118a0](https://github.com/tinfoil-factory/netfoil/commit/ea42977900c864b7b1c42f26c5870c86008118a0) |
| `py-spy-varint-out-of-bounds` | [benfred/py-spy](https://github.com/benfred/py-spy) | MIT | [PR #736 (merge commit 9ab9703c9b5fffe65d10f25ec5ddb86b0e0450](https://github.com/benfred/py-spy/pull/736) |
| `qbee-agent-symlink-write` | [qbee-io/qbee-agent](https://github.com/qbee-io/qbee-agent) | Apache-2.0 | [0fdf8e411de5d0c142ae2590cf1c54bdfc2e529a](https://github.com/qbee-io/qbee-agent/commit/0fdf8e411de5d0c142ae2590cf1c54bdfc2e529a) |
| `react-refresh-sourcemap-leak` | [pmmmwh/react-refresh-webpack-plugin](https://github.com/pmmmwh/react-refresh-webpack-plugin) | MIT | [PR #537 (merge commit 77be80c859d44ff4528478e754aedf5f6df489](https://github.com/pmmmwh/react-refresh-webpack-plugin/pull/537) |
| `safari-mcp-js-escape-injection` | [achiya-automation/safari-mcp](https://github.com/achiya-automation/safari-mcp) | MIT | [23f1319defefd2c5cbd06b23189ab01876a8c5d3](https://github.com/achiya-automation/safari-mcp/commit/23f1319defefd2c5cbd06b23189ab01876a8c5d3) |
| `tornado-header-folding-quadratic` | [tornadoweb/tornado](https://github.com/tornadoweb/tornado) | Apache-2.0 | [1b7a1dc9f340f52de929852e8125aa12f25297c9](https://github.com/tornadoweb/tornado/commit/1b7a1dc9f340f52de929852e8125aa12f25297c9) |
| `vault-webhook-addr-ssrf` | [bank-vaults/vault-secrets-webhook](https://github.com/bank-vaults/vault-secrets-webhook) | Apache-2.0 | [76db45976fee0f54cafd94dffa425e6b542f65a0](https://github.com/bank-vaults/vault-secrets-webhook/commit/76db45976fee0f54cafd94dffa425e6b542f65a0) |
| `wllama-test-layout-refactor` | [ngxson/wllama](https://github.com/ngxson/wllama) | MIT | [PR #350 (merge commit b5e8664f14ef97ee6b251c6656f34068cf8750](https://github.com/ngxson/wllama/pull/350) |

## Notices

- **[achiya-automation/safari-mcp](https://github.com/achiya-automation/safari-mcp)** (MIT): Copyright (c) 2026 Achiya Cohen
- **[bank-vaults/vault-secrets-webhook](https://github.com/bank-vaults/vault-secrets-webhook)** (Apache-2.0): see the LICENSE file in the repository for the full terms
- **[benfred/py-spy](https://github.com/benfred/py-spy)** (MIT): Copyright (c) 2018-2019 Ben Frederickson
- **[eslint/eslint](https://github.com/eslint/eslint)** (MIT): see the LICENSE file in the repository for the full terms
- **[ether/etherpad](https://github.com/ether/etherpad)** (Apache-2.0): Copyright 2013 THE ETHERPAD FOUNDATION
- **[FasterXML/jackson-databind](https://github.com/FasterXML/jackson-databind)** (Apache-2.0): see the LICENSE file in the repository for the full terms
- **[helm/helm](https://github.com/helm/helm)** (Apache-2.0): Copyright 2016 The Kubernetes Authors All Rights Reserved
- **[ipython/ipython](https://github.com/ipython/ipython)** (BSD-3-Clause): see the LICENSE file in the repository for the full terms
- **[kubeflow/pipelines](https://github.com/kubeflow/pipelines)** (Apache-2.0): see the LICENSE file in the repository for the full terms
- **[mem0ai/mem0](https://github.com/mem0ai/mem0)** (Apache-2.0): Copyright [2023] [Taranjeet Singh]
- **[ngxson/wllama](https://github.com/ngxson/wllama)** (MIT): Copyright (c) 2024 Xuan Son NGUYEN
- **[pmmmwh/react-refresh-webpack-plugin](https://github.com/pmmmwh/react-refresh-webpack-plugin)** (MIT): Copyright (c) 2019 Michael Mok
- **[qbee-io/qbee-agent](https://github.com/qbee-io/qbee-agent)** (Apache-2.0): Copyright 2023 qbee.io
- **[spf13/cobra](https://github.com/spf13/cobra)** (Apache-2.0): see the LICENSE file in the repository for the full terms
- **[tinfoil-factory/netfoil](https://github.com/tinfoil-factory/netfoil)** (Apache-2.0): see the LICENSE file in the repository for the full terms
- **[tornadoweb/tornado](https://github.com/tornadoweb/tornado)** (Apache-2.0): see the LICENSE file in the repository for the full terms
