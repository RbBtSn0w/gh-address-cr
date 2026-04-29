## [2.0.2](https://github.com/RbBtSn0w/gh-address-cr/compare/v2.0.1...v2.0.2) (2026-04-29)

### Bug Fixes

* include refactor commits in patch releases ([654dee2](https://github.com/RbBtSn0w/gh-address-cr/commit/654dee27b49668a9ce08cddb849632aefaa4a822))

## [2.0.1](https://github.com/RbBtSn0w/gh-address-cr/compare/v2.0.0...v2.0.1) (2026-04-29)

### Bug Fixes

* trigger PyPI release after trusted publisher migration ([9447fa6](https://github.com/RbBtSn0w/gh-address-cr/commit/9447fa6e5d78353ec77d66ea5dd75094a115335f))

## [2.0.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.5.1...v2.0.0) (2026-04-29)

### ⚠ BREAKING CHANGES

* **001-007:** release v2

### Features

* **001-007:** release v2 ([bf5dd4a](https://github.com/RbBtSn0w/gh-address-cr/commit/bf5dd4a61ef220480397b8df3a25110ee3645d71))

### Bug Fixes

* harden semantic-release parsing ([#14](https://github.com/RbBtSn0w/gh-address-cr/issues/14)) ([d0b3e35](https://github.com/RbBtSn0w/gh-address-cr/commit/d0b3e35a15308b7640972ae8344ce288aadba52e))

## [1.5.1](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.5.0...v1.5.1) (2026-04-23)

### Bug Fixes

* Enforce reply evidence across sync and resolve paths ([#11](https://github.com/RbBtSn0w/gh-address-cr/issues/11)) ([378b65e](https://github.com/RbBtSn0w/gh-address-cr/commit/378b65e12cf023411b79014d3850134b4cc87d4d))

## [1.5.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.4.1...v1.5.0) (2026-04-21)

### Features

* add submit-action public command for recovering from WAITING_FOR_FIX ([#7](https://github.com/RbBtSn0w/gh-address-cr/issues/7)) ([aad1af4](https://github.com/RbBtSn0w/gh-address-cr/commit/aad1af48df7103165d7959e5fcc07b1368cdfc96))

## [1.4.1](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.4.0...v1.4.1) (2026-04-19)

### Bug Fixes

* clarify feedback reporting target and source context ([#5](https://github.com/RbBtSn0w/gh-address-cr/issues/5)) ([4340b20](https://github.com/RbBtSn0w/gh-address-cr/commit/4340b2057a5096748e1e452120c1130e02091082))

## [1.4.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.3.0...v1.4.0) (2026-04-18)

### Features

* add hosted telemetry relay and fix replies ([#4](https://github.com/RbBtSn0w/gh-address-cr/issues/4)) ([ab85d07](https://github.com/RbBtSn0w/gh-address-cr/commit/ab85d07cae0c43e0641758282e5a032e238dced1))

## [1.3.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.2.0...v1.3.0) (2026-04-18)

### Features

* add agent feedback issue reporting ([#3](https://github.com/RbBtSn0w/gh-address-cr/issues/3)) ([9b373c8](https://github.com/RbBtSn0w/gh-address-cr/commit/9b373c861d9d1bea0d8954ac9be7e530d23b4f65))

## [1.2.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.1.1...v1.2.0) (2026-04-16)

### Features

* upgrade gh-address-cr to a python session workflow ([#2](https://github.com/RbBtSn0w/gh-address-cr/issues/2)) ([f2c153b](https://github.com/RbBtSn0w/gh-address-cr/commit/f2c153b4db443621d3b8e979476dd95c513fe7e9))

## [1.1.1](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.1.0...v1.1.1) (2026-04-09)

### Bug Fixes

* avoid stale line reuse in batch resolve ([86252ee](https://github.com/RbBtSn0w/gh-address-cr/commit/86252ee84e1d5f65c553ec1884b497be0304cb74))
* harden batch resolve parsing ([6016acc](https://github.com/RbBtSn0w/gh-address-cr/commit/6016accca30e8b2e5d72ccd2c21882be7d6a2617))
* tighten gh-address-cr agent guardrails ([8c85166](https://github.com/RbBtSn0w/gh-address-cr/commit/8c851666ebe6b60fe00f5a4afd2105aaa3d4459b))
* tighten review comment follow-ups ([62e374d](https://github.com/RbBtSn0w/gh-address-cr/commit/62e374d10a99f870207d4a05f6d64c82f88f331e))

## [1.1.0](https://github.com/RbBtSn0w/gh-address-cr/compare/v1.0.0...v1.1.0) (2026-04-03)

### Features

* enhance reply generation with new clarify mode and remove deprecated reply_fixed script ([55a4396](https://github.com/RbBtSn0w/gh-address-cr/commit/55a439641fe5b5b9f355127af15cac4320d8f09e))
* expand README with detailed core workflow diagram for PR review resolution ([ed57cd9](https://github.com/RbBtSn0w/gh-address-cr/commit/ed57cd956428b0a384ed74b5ecf500056ef0381c))

## 1.0.0 (2026-03-24)

### Features

* add semantic-release workflow and update contributing guidelines for automated releases ([b8c363e](https://github.com/RbBtSn0w/gh-address-cr/commit/b8c363e35506ad373e3ff9fa4a578a9fd9564f55))
* enhance state management with user cache directory and improved clean_state script options ([796f11e](https://github.com/RbBtSn0w/gh-address-cr/commit/796f11e03f37b10ad1ba1ae39cfce20bbc3ec628))
* publish gh-address-cr bash skill with audit workflow ([7131ba8](https://github.com/RbBtSn0w/gh-address-cr/commit/7131ba8cacb49eb0dcac5190359054dfda5212e9))
