# First public release plan

Target: publish `pi-agent-python-sdk==0.1.0`, imported as `pi_agent`, with
reviewed source, reproducible validation, and verified PyPI installation.
A checked-in plan or a green build does not establish publication.

The repository and distribution are named `pi-agent-python-sdk`; Python imports
remain `pi_agent`. On 2026-09-18, neither PyPI nor TestPyPI listed a project under
the selected name. Confirm availability during publisher setup; a missing index
entry does not reserve the name or guarantee registration.

## Current state

Snapshot: 2026-09-18. Repository visibility is private; `main` is unprotected;
`testpypi` and `pypi` environments are absent. The current automation account has
push access but no repository administration permission. Package-index account
settings cannot be inspected through that GitHub account. The package version is
`0.1.0rc1`; no publication is claimed.

The remaining implementation PRs are #15 (runtime), #16 (documentation),
#17 (package/import names), and #18 (agent instructions). Refresh their state
before acting: approvals and merges may advance while launch work proceeds.

## Reviewable changes

Prepare focused PRs in this order:

1. **Launch plan:** this checklist and corrected owner setup guidance.
2. **Publishing verification:** bind rehearsal dispatches to a reviewed commit,
   require CI for that commit, verify the downloaded TestPyPI wheel before PyPI
   promotion, and verify the final PyPI installation.
3. **Project rename:** align distribution metadata, repository links, publishing
   configuration, and checks with `pi-agent-python-sdk` before the rehearsal.
4. **Final release candidate:** a draft PR for `0.1.0` metadata, lockfile,
   changelog, release notes, and documentation links pinned to `v0.1.0`.
   Keep it draft until the `0.1.0rc1` rehearsal succeeds.

Keep each PR open until the user approves that specific PR. Squash approved PRs
in dependency order; replay each remaining branch's own commits on the updated
base, retarget the next PR, and rerun its checks. Leave auto-merge off.

## 1. Owner setup: repository and publishers

The repository owner performs these account-level steps. The agent can prepare
and inspect the configuration, but its current credentials cannot change it.

- [ ] Review the source and history that will become public. Record the owner's
  approval of the visibility change; in repository Settings → General → Danger
  Zone, make the repository public when ready for that exposure.
- [ ] Protect `main`: require the `required` status check, require the branch to
  be current with its base, and enforce protection for administrators. Preserve
  the separate user-approval requirement for every merge.
- [ ] Enable squash merging and disable merge commits, rebase merging, and
  auto-merge in repository settings.
- [ ] Create `testpypi` and `pypi` environments. Require reviewer `cheenulabs`;
  allow that owner to approve their own dispatched deployment. Disable protection
  bypass where available. Permit only branch `main` and tags `v*` for TestPyPI,
  and tags `v*` for PyPI.
- [ ] Confirm the selected name remains available and register the pending
  publishers below in the intended owner's separate TestPyPI and PyPI accounts.
  No upload token is needed.

For this personal repository, required environment reviewers may require public
visibility: GitHub Free/Pro/Team provide that protection only for public
repositories. Change visibility before configuring those protections if the
current plan does not support them privately. Do not silently omit reviewers.

| Publisher field | TestPyPI | PyPI |
| --- | --- | --- |
| Project | `pi-agent-python-sdk` | `pi-agent-python-sdk` |
| GitHub owner | `cheenulabs` | `cheenulabs` |
| Repository | `pi-agent-python-sdk` | `pi-agent-python-sdk` |
| Workflow filename | `publish.yml` | `publish.yml` |
| Environment | `testpypi` | `pypi` |

Register via [TestPyPI publishing](https://test.pypi.org/manage/account/publishing/)
and [PyPI publishing](https://pypi.org/manage/account/publishing/). Confirm the
name remains available. Pending registration does not reserve the name.
Record confirmation of both publisher registrations without credentials.

Completion evidence: public repository URL, protected `main`, environment
reviewer/ref policies, and account-holder confirmation of both publisher records.

## 2. Land the reviewed implementation and rehearsal workflow

- [ ] Obtain specific PR approvals and finish the stack through the project
  rename PR, including publishing verification; leave the final-version PR open.
- [ ] Run all CONTRIBUTING.md checks on the resulting `main` commit and wait for
  the complete CI matrix. Record its full SHA and CI URL.
- [ ] Build `0.1.0rc1`, inspect the wheel/sdist and README metadata, and record
  SHA-256 digests of both artifacts. Ensure no earlier upload consumed the version.

Completion evidence: merged PR URLs, exact rehearsal SHA, green CI URL,
artifact names/digests, and verified publisher configuration.

## 3. TestPyPI rehearsal

- [ ] Present that candidate and setup evidence for explicit TestPyPI publication
  approval. After approval, dispatch `publish.yml` from `main` with the reviewed
  full commit SHA. If `main` moved, validate and approve the new candidate first.
- [ ] The owner approves the `testpypi` deployment after checking the run's SHA.
- [ ] Download the published wheel from TestPyPI in a clean environment; verify
  it matches the reviewed artifact, imports `pi_agent`, includes `py.typed`, and
  runs both clients against a synthetic executable outside the checkout.
- [ ] Inspect the TestPyPI project page and documentation links. Record the run
  and package URLs. Keep final-version preparation separate from rehearsal proof.

Completion evidence: successful TestPyPI upload and index-install verification,
plus rendered package-page checks. Local-wheel installation alone is insufficient.

## 4. Final release candidate

- [ ] Review the draft `0.1.0` PR after the successful rehearsal. Restack it on
  the validated base and rerun all checks before its approved squash merge.
- [ ] Confirm final version, lockfile, release notes, and `v0.1.0` documentation
  URLs agree. Those tag URLs become live when the approved tag is created.
- [ ] Validate the exact release commit and record its full SHA and CI URL.
- [ ] Present the release candidate and evidence for explicit approval to create
  tag `v0.1.0`, publish the GitHub release, and upload to the indexes.

Completion evidence: approved final PR, green CI for the release SHA, prepared
release notes, and explicit publication approval. Preparation creates no tag.

## 5. Publish and verify

- [ ] After approval, tag the reviewed commit and publish its GitHub release.
- [ ] Approve TestPyPI publication of the final artifacts and require its
  index-install verification to pass before approving the PyPI deployment.
- [ ] Publish the same wheel and sdist to PyPI. Verify the index digests and
  downloaded-wheel installation; confirm the public quickstart and links work.
- [ ] Record the GitHub release, workflow, TestPyPI, and PyPI URLs with the release
  SHA and artifact digests. Mark this plan complete only when all evidence exists.

If upload succeeds but verification fails, do not promote or report success.
Diagnose the failed run. A corrected artifact needs a new version; avoid
re-uploading conflicting files. If a published release must be withdrawn, decide
on yanking with the owner and record the reason; do not silently remove it.

Operational commands and full validation are in [releasing](releasing.md) and
[CONTRIBUTING.md](../CONTRIBUTING.md).

Sources: [GitHub environment availability](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[PyPI pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
