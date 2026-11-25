# Changelog

## [1.1.0](https://github.com/mattjenks/cta-skills/compare/build-v1.0.2...build-v1.1.0) (2026-11-25)


### Features

* **learn:** weekly skill-learning report, decide, deliver and schedule ([64dc805](https://github.com/mattjenks/cta-skills/commit/64dc8050c27516b385d6310beeefe7dfd966af3c))

## [1.0.2](https://github.com/mattjenks/cta-skills/compare/build-v1.0.1...build-v1.0.2) (2026-11-24)


### Bug Fixes

* **build:** design slug rule drops words no hook matches ([616c52d](https://github.com/mattjenks/cta-skills/commit/616c52dd5f1513bd049551f21db983151570ad4f))
* **build:** final-review wording keeps back-to-open contract ([62f901f](https://github.com/mattjenks/cta-skills/commit/62f901f96441b1006022a5ec53b1e69fb66a877a))
* **build:** proposals eval case is one YAML document ([e46bc29](https://github.com/mattjenks/cta-skills/commit/e46bc2944ff5d39afa9f578dfae4e4f763a54391))
* **build:** review applies the reviewer's answer to proposals, passes findings path ([2d28053](https://github.com/mattjenks/cta-skills/commit/2d280536096840cef9169d5b90db3237f84a724b))
* **build:** review re-asks the reviewer once on unanswered proposals ([7814ba1](https://github.com/mattjenks/cta-skills/commit/7814ba10142c26221e9c6701d0a7b3aa4a949b7d))

## [1.0.1](https://github.com/mattjenks/cta-skills/compare/build-v1.0.0...build-v1.0.1) (2026-11-23)


### Bug Fixes

* **build:** commit gate judges only the lines a commit changes ([17aac31](https://github.com/mattjenks/cta-skills/commit/17aac31b30e3eb4d265a410c1adffff18e45f3a6))
* **build:** commit gate judges only the lines a commit changes ([db15361](https://github.com/mattjenks/cta-skills/commit/db15361cadb12d5d06bdcc1d5ec038295bbd9cbf))
* drop $schema from plugin.json so claude.ai stops warning ([39a07e1](https://github.com/mattjenks/cta-skills/commit/39a07e1a82be0c0111d78edac92a17a8e49e8396))
* drop $schema from plugin.json so claude.ai stops warning ([047df8c](https://github.com/mattjenks/cta-skills/commit/047df8cc0edf2cf728239c7bfb1481e117319495))

## [1.0.0](https://github.com/mattjenks/cta-skills/compare/build-v0.1.0...build-v1.0.0) (2026-11-23)


### ⚠ BREAKING CHANGES

* **build:** security_gate.py is removed; hooks.json wires gate_guard.py and the commit gate requires the git hooks to be installed (core.hooksPath).

### Features

* **build:** commit gate as git hooks ([7b3e021](https://github.com/mattjenks/cta-skills/commit/7b3e0210d4d3aa363b5a177632a43cc285b12d30))
* **build:** commit, pr, review-pr, retro, debug, fix-issue, loop ([185659e](https://github.com/mattjenks/cta-skills/commit/185659ea08f9c52413f74c767f2a3467105a2b64))
* **build:** implement and validate skills ([b4acb41](https://github.com/mattjenks/cta-skills/commit/b4acb41c7061053526eb0155ec63dac1a322cb3f))
* **build:** knowledge-base worktrees and project mapping ([1d6b29a](https://github.com/mattjenks/cta-skills/commit/1d6b29aaee2d75de2e90c293d7f283256e21fe92))
* **build:** prime, design and plan skills ([9ae443f](https://github.com/mattjenks/cta-skills/commit/9ae443f10e914a3d4604135322dc380977fc7541))
* **build:** scaffold build plugin ([76dc434](https://github.com/mattjenks/cta-skills/commit/76dc434ba561a7556d7d3b2bff91a31c70320fed))
* **build:** scanners and findings record ([67d573f](https://github.com/mattjenks/cta-skills/commit/67d573f86ba799c66dc20b9000c2b68fcc2ad2a2))
* **build:** secure and review skills ([d8a5abb](https://github.com/mattjenks/cta-skills/commit/d8a5abbf9d17d1500b5c5d03be53980094f236b6))
* **build:** security gate and finding guard hooks ([5f5e8f8](https://github.com/mattjenks/cta-skills/commit/5f5e8f8084dee0c181a2f5e6285537b684f3986f))
* **build:** size reviews to the change; never stop on findings ([092dbc4](https://github.com/mattjenks/cta-skills/commit/092dbc45f39f76706f5454d475776c8674f52f95))
* **build:** size the reviews to the change and never stop on findings ([d9caebf](https://github.com/mattjenks/cta-skills/commit/d9caebf1604921722b183e9dcf6d578a77a31ab2))
* **build:** workspace, brief and review-package helpers ([7358014](https://github.com/mattjenks/cta-skills/commit/73580148ff043094560a0b72afef8005aa099dda))
* **core:** skill budgets, evals and model map ([39611ea](https://github.com/mattjenks/cta-skills/commit/39611ea8378a6b872d4bfbfe343e32fb70d792c4))
* CTA stage 2 build plugin ([517ef08](https://github.com/mattjenks/cta-skills/commit/517ef08a45de86ba6c2d03ba110d30bfa2cdb79c))


### Bug Fixes

* **build:** builder commits task work; dependency check before push ([dbf1964](https://github.com/mattjenks/cta-skills/commit/dbf19648e584b7ce9a3fa9ccd523196f8b4041d6))
* **build:** carry ledger leftovers and every verify exit-5 entry into the PR ([a622a26](https://github.com/mattjenks/cta-skills/commit/a622a26d56558285677736d5633fe82c65f1e6ff))
* **build:** classify ignore files, isolate git config ([f0aec46](https://github.com/mattjenks/cta-skills/commit/f0aec46865e1820c03d520d7af494c28f65c027b))
* **build:** close gate and guard bypasses ([4cc8621](https://github.com/mattjenks/cta-skills/commit/4cc8621ec7665d278d77b75bf8403dda5a52a678))
* **build:** close scanner false negatives (nested manifests, top-level, typechange, ignores) ([7d61362](https://github.com/mattjenks/cta-skills/commit/7d613621599f6b689bfead5109a62748a8f29694))
* **build:** default-branch check before builder, fix diff from commit range ([14f855f](https://github.com/mattjenks/cta-skills/commit/14f855fe87036fb29f5d5038255469104ac780bb))
* **build:** exclude only transient .cta paths; brief parity fixes ([7b6a244](https://github.com/mattjenks/cta-skills/commit/7b6a244a28d083fb74efdba5a614642bcc34a2a8))
* **build:** gate state in git common dir, global hooks chain, guard type safety ([a216c3e](https://github.com/mattjenks/cta-skills/commit/a216c3edb806dd062e912d65575c668de18c57d8))
* **build:** implement dependency check before commit, sonnet re-review floor, small-path workspace ([dfb0fcb](https://github.com/mattjenks/cta-skills/commit/dfb0fcb39ef7cb4750734344b6ffe87052dd1c7d))
* **build:** isolate gitleaks source, nosem, honest audit coverage ([e0ed923](https://github.com/mattjenks/cta-skills/commit/e0ed92382107218c3ce19052b53f725b5cf96443))
* **build:** kbwork resolves a git worktree to its main checkout for [projects] ([d1caf54](https://github.com/mattjenks/cta-skills/commit/d1caf54ffc36d061b49fd0f6e8fd703237e74e78))
* **build:** kbwork resolves worktrees to the main checkout ([2972e45](https://github.com/mattjenks/cta-skills/commit/2972e45ffa402e5d48108762d7751c4f3d395d6c))
* **build:** persist design approval, per-dispatch model check, push handling ([31d4fa2](https://github.com/mattjenks/cta-skills/commit/31d4fa2d6f62dd7a01a4049251c659af816c0452))
* **build:** retro_event tells an HTTP rejection from an unreachable collector; sharper evals ([dd39b81](https://github.com/mattjenks/cta-skills/commit/dd39b8169f45fe6fa66d3b374384738c00d9df30))
* **build:** safe config edits, safer close_build, strict kb repo check ([a1d4d87](https://github.com/mattjenks/cta-skills/commit/a1d4d871fd89b2ae5c834543c10a7e517b4da929))
* **build:** scan ignore-file content, exact audit coverage ([a940f79](https://github.com/mattjenks/cta-skills/commit/a940f79e3986e84731e85efeba02f7eda2c59f0f))
* **build:** scan staged/committed content, fail closed on scanner gaps ([5420197](https://github.com/mattjenks/cta-skills/commit/54201974b4feea926a7f7cad0d9e1d157243d06d))
* **build:** secure rescans on finish, reopens regressions; discriminating evals ([75469f5](https://github.com/mattjenks/cta-skills/commit/75469f58acddcd586a0c5440ec7bb43641059425))

## 0.1.0 — scaffold

- New `build` plugin, installed as `build@cta`. Skills will be invoked as `/build:<skill>`.
- Plugin skeleton only: manifest, changelog and test directory. No skills or hooks yet.
