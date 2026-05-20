# Contributing

Thank you for your interest in contributing.

## Forking and Branching

1. Fork the repository to your own GitHub account.
2. Create a topic branch from the default branch.
3. Use a clear branch name such as `feat/<short-description>` or `fix/<short-description>`.

Example:

```bash
git checkout -b feat/add-ddi-wrapper
```

## Pull Request Guidelines

1. Keep pull requests focused and small enough to review efficiently.
2. Include a clear description of changes, rationale, and testing performed.
3. Reference related issues when applicable.
4. Ensure CI passes before requesting review.
5. Update documentation when behavior, configuration, or operational expectations change.

## Coding Standards

1. Preserve existing project structure and coding style.
2. Prefer clear, explicit code over clever shortcuts.
3. Add tests for new behavior and regression coverage for bug fixes.
4. Avoid introducing unrelated refactors in feature or fix pull requests.
5. Include SPDX headers for new source files where applicable.

## Commit Quality

1. Keep commits clean, atomic, and logically grouped.
2. Use meaningful commit messages that explain intent and scope.
3. Avoid mixing formatting-only and functional changes in the same commit unless required.

## Licensing of Contributions

By submitting code, documentation, or other contributions to this repository, you agree that your contributions are licensed under the Apache License 2.0.

## NOTICE File Policy

A `NOTICE` file is not required by default for this repository.
Add a `NOTICE` file only when third-party attribution obligations exist that are not already satisfied by dependency licenses and package metadata.
