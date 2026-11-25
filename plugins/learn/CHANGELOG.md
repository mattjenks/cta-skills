# Changelog

## [0.2.0](https://github.com/mattjenks/cta-skills/compare/learn-v0.1.0...learn-v0.2.0) (2026-11-25)


### Features

* **learn:** cta-reports pane to decide recommendations ([01fc0ec](https://github.com/mattjenks/cta-skills/commit/01fc0ecac838fd2f5d0a40696d7fa2cbd72a46da))
* **learn:** decide skill files issues and logs decisions ([5da9130](https://github.com/mattjenks/cta-skills/commit/5da9130bc34a18a946fd87f37750192408b8ea32))
* **learn:** deliver skill with config recipient and fallback ([486991e](https://github.com/mattjenks/cta-skills/commit/486991e1d560b7c474826fe8373692a79d139028))
* **learn:** gather the week from Prometheus and Loki ([6b07227](https://github.com/mattjenks/cta-skills/commit/6b0722744b13ee3fa918ad7fec1b8d2974ae2a6a))
* **learn:** plugin scaffold and [learn] config ([09e435a](https://github.com/mattjenks/cta-skills/commit/09e435adc5330b02c18555e1acdb67341e28bb67))
* **learn:** report model with markdown, HTML and JSON views ([110a136](https://github.com/mattjenks/cta-skills/commit/110a1367239befa1444349ff10cc46c4ca1a6fd3))
* **learn:** report skill ([c471eb1](https://github.com/mattjenks/cta-skills/commit/c471eb132c3894143d81ea1cd5e3f8493553a039))
* **learn:** rot checks for skills, connectors, rules and permissions ([0ecffa0](https://github.com/mattjenks/cta-skills/commit/0ecffa0ee21d1eb25da343577afd3c494799cd84))
* **learn:** schedule skill using desktop scheduled tasks ([ceda15d](https://github.com/mattjenks/cta-skills/commit/ceda15d5be7d71213a5781b472ae9a03b34eacc9))
* **learn:** signals and capped recommendation candidates ([5f06d96](https://github.com/mattjenks/cta-skills/commit/5f06d96fad7a6c62e8f5a5e6ca14c88d5989e7bb))
* **learn:** weekly skill-learning report, decide, deliver and schedule ([64dc805](https://github.com/mattjenks/cta-skills/commit/64dc8050c27516b385d6310beeefe7dfd966af3c))
* **telemetry:** learn decisions panel ([9a50e4f](https://github.com/mattjenks/cta-skills/commit/9a50e4f1bcee5d6762f0058579c4fcf41e93f4de))


### Bug Fixes

* **learn:** attribute tool failures to skills by session ([8de26b9](https://github.com/mattjenks/cta-skills/commit/8de26b93dffd11ace7ecf9e37be708d06ef36e14))
* **learn:** decide sets up the worktree before filing and ignores inherited gitleaks config ([475a0fa](https://github.com/mattjenks/cta-skills/commit/475a0fa493fa850b1d1f6fda06356bff208f62a8))
* **learn:** decide tests run without a real gitleaks ([397947d](https://github.com/mattjenks/cta-skills/commit/397947d94098c7919b71cb7c1a1c59d86b63d6df))
* **learn:** decisions reach the next report, and the decisions branch restarts after its PR merges ([24077e4](https://github.com/mattjenks/cta-skills/commit/24077e4fb2ee6b403a6eaa36a3e0e42b0410fc99))
* **learn:** delivery record never writes the live kb checkout ([079b345](https://github.com/mattjenks/cta-skills/commit/079b3452e1fa694b4ae1f52d00880c54b2d75ec8))
* **learn:** delivery record reaches the next report ([bae2869](https://github.com/mattjenks/cta-skills/commit/bae28699768b85bab4bf0a8db8583ebd89fdee0e))
* **learn:** exact backlog duplicate match ([9dd6ae6](https://github.com/mattjenks/cta-skills/commit/9dd6ae630ac709ec3144f3f3437fe63b6da3885b))
* **learn:** exclude work organizations instead of allow-listing ([572687c](https://github.com/mattjenks/cta-skills/commit/572687c1404430569f03928b6f3d27bd36efaac6))
* **learn:** missing Loki data is no data, and one skill's counts are not doubled across orgs ([2e106b3](https://github.com/mattjenks/cta-skills/commit/2e106b3421a26c7bec1fd865213ccc52ee31f9c7))
* **learn:** read failures from tool_result, use exact Grafana panel titles ([6c2df9d](https://github.com/mattjenks/cta-skills/commit/6c2df9dbfa8e9fc0d92900c73cef17e396ccc5fe))
* **learn:** report render paths, backlog overflow and link guard ([b4e6235](https://github.com/mattjenks/cta-skills/commit/b4e6235b1f3aff06c6b5a94316ae24f24c40c9b3))
* **learn:** report skill steps in executable order ([fc068ba](https://github.com/mattjenks/cta-skills/commit/fc068ba22f3ef7c888bff84be2a300382be1c205))
* **learn:** sanitize enforces the S1 name, path and line rules ([809eafd](https://github.com/mattjenks/cta-skills/commit/809eafd8630bbbba54eae6339e024cde67676229))
* **learn:** schedule eval cases are one YAML document ([3d2b37c](https://github.com/mattjenks/cta-skills/commit/3d2b37c3ece1e0da2b9612ccd2d24decc35f3415))
* **learn:** use max_over_time for cost and tokens, drop dead code ([a9358fa](https://github.com/mattjenks/cta-skills/commit/a9358fae8a8021ab3009ef4ea7289b4cccdc5ad3))

## 0.1.0

* Initial scaffold: plugin manifest and `[learn]` config loader.
