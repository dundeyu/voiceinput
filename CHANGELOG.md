# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning in a lightweight form.

## [0.1.0] - 2026-03-21

### Added

- Terminal voice input workflow with keyboard-driven recording controls
- Offline-oriented FunASR integration with configurable model and VAD paths
- Automatic clipboard copy after successful recognition
- Language switching for Chinese, English, and Japanese
- Text post-processing for filler-word filtering and vocabulary correction
- Packaged `voice` command via `pyproject.toml`
- Test suite based on `pytest`
- GitHub CI workflow for macOS
- Issue templates and pull request template
- Open-source project basics including README, LICENSE, CONTRIBUTING, and example config

### Changed

- Reduced noisy terminal output during model loading and inference
- Improved `bin/voice` so it no longer depends on a machine-specific absolute path
- Split runtime and development dependencies
- Switched configuration files from YAML to JSON and removed the `PyYAML` dependency
- Unified the default VAD model path into the project-local `models/` directory

### Fixed

- Avoided terminal corruption caused by third-party progress output
- Fixed volume bar rendering so partial volume no longer appears as fully filled
