# Releasing the package

The package is not yet published. Local build validation is separate from a
TestPyPI rehearsal, GitHub CI, and a public PyPI release. Complete all of them
before calling the first release finished.

## One-time repository and index setup

The repository belongs to the personal GitHub account `cheenulabs`. Its owner
must configure visibility, branch protection, and environments; collaborator
push access does not grant those settings. The authenticated package-index
account holder must register the publishers separately on each index.

- In repository Settings → General → Danger Zone, make
  `cheenulabs/pi-coding-agent-python-client` public. Review and merge the
  remaining milestone PRs in order.
- After the CI workflow runs, use Settings → Branches to protect `main`.
  Require the status check named `required` and require branches to be up to
  date before merging. Confirm all supported Python and operating-system jobs
  actually pass. An additional human PR approval is optional; the required
  status check is the automated gate.
- Confirm the distribution name `pi-coding-agent-client` is available on
  PyPI and TestPyPI. The chosen import is `pi_coding_agent_client`; the license
  is MIT. Recheck public metadata URLs before release.
- In Settings → Environments, create `testpypi` and `pypi`, each with
  `cheenulabs` as a required reviewer. Allow self-review if that same account
  will both dispatch and approve a deployment. Any deployment branch/tag
  restrictions must allow `main` for the TestPyPI rehearsal and release tags
  such as `v0.1.0` for both environments.
- Register a pending publisher in the intended owner's separate
  [TestPyPI account](https://test.pypi.org/manage/account/publishing/) and
  [PyPI account](https://pypi.org/manage/account/publishing/), using these fields:

  | Field | TestPyPI | PyPI |
  |---|---|---|
  | Project name | `pi-coding-agent-client` | `pi-coding-agent-client` |
  | GitHub owner | `cheenulabs` | `cheenulabs` |
  | Repository | `pi-coding-agent-python-client` | `pi-coding-agent-python-client` |
  | Workflow filename | `publish.yml` | `publish.yml` |
  | Environment | `testpypi` | `pypi` |

  A pending publisher creates the initial project on a successful upload; it
  does not reserve the name. No long-lived upload token belongs in the
  repository or ordinary PR jobs.

These external settings cannot be established by committing YAML alone.
After setup, the selected reviewer must approve the actual deployment jobs
when GitHub presents them.

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
[pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[personal repository permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository),
[branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule),
[environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[packaging release workflow](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
