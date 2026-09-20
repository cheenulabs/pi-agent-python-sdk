# Releasing the package

Local build validation is separate from a TestPyPI rehearsal, GitHub CI, and a
public PyPI release. For each release, validate the reviewed commit and built artifacts before
publication, then verify the copies downloaded from both indexes.

## 0.2.1 release verification

The 0.2.1 metadata and release notes describe the reviewed patch candidate.
Confirm the `v0.2.1` GitHub release and successful TestPyPI/PyPI verification
jobs before recording 0.2.1 as released or pinning it in a deployed consumer.

## 0.2.0 release verification

The 0.2.0 metadata and release notes describe the reviewed release candidate.
A source checkout or version number alone does not prove publication. Confirm
the `v0.2.0` GitHub release and successful TestPyPI/PyPI verification jobs before
recording 0.2.0 as released or pinning it in a deployed consumer. This keeps the
same verification requirement before and after the approved publication.

## Approval and scope

Merge each PR only after explicit approval. Publication, including a
TestPyPI rehearsal, requires separate explicit approval after the release
candidate and publishing setup are ready for review.

The [first public release plan](launch-plan.md) records the original setup.
Subsequent releases reuse the existing publishers and approval workflow. The
release version follows the actual API changes: 0.2.0 includes the command-result
migration from 0.1.0 and retains `run()`, streaming, and `RunResult`.
[#41](https://github.com/cheenulabs/pi-agent-python-sdk/issues/41) tracks candidate
validation, approval, publication, and separate Cheenulabs adoption.

## One-time repository and index setup

The repository belongs to the personal GitHub account `cheenulabs`. Its owner
must configure visibility, branch protection, and environments; collaborator
push access does not grant those settings. The authenticated package-index
account holder must register the publishers separately on each index.

- In repository Settings → General → Danger Zone, make
  `cheenulabs/pi-agent-python-sdk` public when the user authorizes
  publication. This is not needed to review the private PRs.
- After the CI workflow runs, use Settings → Branches to protect `main`.
  Require the status check named `required` and require branches to be up to
  date before merging. Confirm all supported Python and operating-system jobs
  actually pass. The user's explicit approval of each PR is mandatory even
  when GitHub does not enforce an approving review through branch protection.
- Use squash merging. In Settings → General → Pull Requests, the owner can
  disable merge commits and rebase merging while leaving squash enabled.
  Follow the review process in [CONTRIBUTING.md](../CONTRIBUTING.md) and
  keep auto-merge off.
- Confirm the distribution name `pi-agent-python-sdk` is available on
  PyPI and TestPyPI. The chosen import is `pi_agent`; the license
  is MIT. Recheck public metadata URLs before release.

For a personal repository on GitHub Free or Pro, required environment reviewers
are available only when the repository is public. Complete the approved
visibility change before configuring those protections if needed.

- In Settings → Environments, create `testpypi` and `pypi`, each with
  `cheenulabs` as a required reviewer. Allow self-review if that same account
  will both dispatch and approve a deployment. Any deployment branch/tag
  restrictions must allow `main` for the TestPyPI rehearsal and release tags
  such as `v0.2.0` for both environments.
- Register a pending publisher in the intended owner's separate
  [TestPyPI account](https://test.pypi.org/manage/account/publishing/) and
  [PyPI account](https://pypi.org/manage/account/publishing/), using these fields:

  | Field | TestPyPI | PyPI |
  |---|---|---|
  | Project name | `pi-agent-python-sdk` | `pi-agent-python-sdk` |
  | GitHub owner | `cheenulabs` | `cheenulabs` |
  | Repository | `pi-agent-python-sdk` | `pi-agent-python-sdk` |
  | Workflow filename | `publish.yml` | `publish.yml` |
  | Environment | `testpypi` | `pypi` |

  A pending publisher creates the initial project on a successful upload; it
  does not reserve the name. No long-lived upload token belongs in the
  repository or ordinary PR jobs.

These external settings cannot be established by committing YAML alone.
After setup, the selected reviewer must approve the actual deployment jobs
when GitHub presents them.

## Prepare the public documentation

Use the tag (for example, `v0.2.0`) as the GitHub release title. Write the body
in `docs/releases/<version>.md`, following the [release notes style](releases/style.md):
lead with user-facing highlights and link to the tagged documentation.

Keep the README and package metadata's documentation links pinned to the release
tag with absolute GitHub URLs. Before publishing a release:

- Merge the approved SDK changes into `main` and validate that release commit.
- Point README documentation, example, source, and license links, plus the
  Documentation and Changelog metadata URLs, at the release tag (for example,
  `blob/v0.2.0/docs/usage.md`). Keep these URLs absolute: PyPI renders the README
  as a package description and does not resolve paths against this repository.
- Replace the source clone instructions with the published-package
  installation command when the package becomes available. Keep source-install
  instructions tied to the release tag if they remain documented.
- Inspect the built wheel's README metadata and check links from the TestPyPI
  project page before publishing the final release.

## Rehearsal and release

1. For a separate TestPyPI rehearsal, use a unique prerelease version such as `0.2.0rc1` in `pyproject.toml` for
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
   uv run mypy --strict examples scripts/check_examples.py scripts/check_parity.py
   uv run python scripts/check_examples.py
   uv run python scripts/check_parity.py
   uv run python scripts/check_upstream.py
   uv run python -m build
   uv run twine check dist/*
   uv run python scripts/check_distribution.py --parity
   ```

3. If a separate rehearsal is needed, after explicit approval to publish it, manually dispatch
   Publish distributions for that reviewed prerelease
   commit from `main`, supplying its full SHA as `expected_sha`. The workflow
   refuses a different ref or SHA and requires successful CI for that commit.
   Approve the `testpypi` environment, then verify the published wheel
   in a fresh environment outside the checkout. Run sync/async smoke scenarios
   against the offline fixture. Do not reuse a version already uploaded to
   TestPyPI; the workflow intentionally does not skip conflicting artifacts.
4. Prepare final `0.2.0` metadata and changelog in a reviewed PR. Ensure all
   required checks pass on the release commit. Only after explicit user approval
   to publish the final release, create tag `v0.2.0` and publish its GitHub
   release with those notes.
5. The release workflow checks that the tag matches the package version,
   runs tests and validation, and builds once. It publishes those exact
   artifacts to TestPyPI, then to PyPI after the environment approvals. The
   upload jobs download the build artifact and never rebuild it. A separate
   TestPyPI verification job must pass before the PyPI environment is offered
   for approval; another verification job checks the final PyPI upload.
6. Verify a clean `pip install pi-agent-python-sdk==0.2.0`, package metadata,
   typing marker, and runnable quickstarts. Mark the release complete only
   after the GitHub and package-index states confirm it.

The verification jobs use `scripts/check_distribution.py --index testpypi` or
`--index pypi` with the original `dist/` artifacts. The script checks both index
file digests, downloads the exact wheel with a pinned SHA-256, and runs sync/async
smoke checks from a fresh environment outside the checkout. These commands are
read-only; they never upload. A missing release is retried briefly, while a
mismatched or yanked artifact fails verification. Keep the build artifacts to
rerun verification without rebuilding potentially different files.

For an approved rehearsal, substitute the validated full commit SHA:

```sh
gh workflow run publish.yml --ref main -f expected_sha=REVIEWED_FULL_COMMIT_SHA
```

Keep distribution directories clean before changing versions so archive checks
do not accidentally inspect an older build. Built wheels and sdists include
only the package and distribution metadata, not npm runtimes or test fixtures.

References: [Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[personal repository permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository),
[branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule),
[environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[packaging release workflow](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
