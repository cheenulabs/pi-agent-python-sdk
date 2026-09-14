# Releasing the package

The package is not yet published. Local build validation is separate from a
TestPyPI rehearsal, GitHub CI, and a public PyPI release. Complete all of them
before calling the first release finished.

## One-time repository and index setup

- Restore access to `cheenulabs/pi-coding-agent-python-client` and push the
  reviewed milestone branches. Create, review, and merge each PR in order.
- Enable the CI workflow and require its `required` check on main. Confirm all
  supported Python and operating-system jobs actually pass.
- Confirm the distribution name `pi-coding-agent-client` is available on
  PyPI and TestPyPI. The chosen import is `pi_coding_agent_client`; the license
  is MIT. Recheck public metadata URLs before release.
- Create `testpypi` and `pypi` GitHub environments with deployment approval
  rules. Configure each index's Trusted Publisher for owner `cheenulabs`,
  repository `pi-coding-agent-python-client`, workflow `publish.yml`, and the
  matching environment. PyPI and TestPyPI are separate accounts/configurations.
  A pending publisher can create the initial project. No long-lived upload
  token belongs in the repository or ordinary PR jobs.

These external settings cannot be established by committing YAML alone.

## Rehearsal and release

1. Use a unique prerelease version such as `0.1.0rc1` in `pyproject.toml` for
   the TestPyPI rehearsal. It is the single package-version source. Update the
   lockfile, changelog, and release notes through a reviewed PR.
2. Run local checks, build and inspect both distributions:

   ```sh
   uv sync --locked --group dev
   npm ci --prefix tests/pi --ignore-scripts --no-audit --no-fund
   uv run pytest -m "not live"
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   uv run python scripts/check_upstream.py
   uv run python -m build
   uv run twine check dist/*
   uv run python scripts/check_distribution.py
   ```

3. Manually dispatch Publish distributions for that reviewed prerelease
   commit, approve the `testpypi` environment, and verify the published wheel
   in a fresh environment outside the checkout. Run sync/async smoke scenarios
   against the offline fixture. Do not reuse a version already uploaded to
   TestPyPI; the workflow intentionally does not skip conflicting artifacts.
4. Prepare final `0.1.0` metadata and changelog in a reviewed PR. Ensure all
   required checks pass on the release commit. Create tag `v0.1.0` and publish
   its GitHub release with those notes.
5. The release workflow checks that the tag matches the package version,
   runs tests and validation, and builds once. It publishes those exact
   artifacts to TestPyPI, then to PyPI after the environment approvals. The
   upload jobs download the build artifact and never rebuild it.
6. Verify a clean `pip install pi-coding-agent-client==0.1.0`, package metadata,
   typing marker, and runnable quickstarts. Mark the release complete only
   after the GitHub and package-index states confirm it.

Keep distribution directories clean before changing versions so archive checks
do not accidentally inspect an older build. Built wheels and sdists include
only the package and distribution metadata, not npm runtimes or test fixtures.

References: [Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[packaging release workflow](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
