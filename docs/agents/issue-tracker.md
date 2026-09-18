# Review specifications

Review the scope and acceptance criteria in the PR description against
[protocol discovery](../discovery.md) and the public API documentation.
Record validation and review findings on the PR.

Use GitHub pull requests in `cheenulabs/pi-coding-agent-python-client`.
For each review, pin the previous milestone commit and compare the proposed
branch against it. Review standards from CONTRIBUTING.md separately from
the PR's declared requirements. A PR need only satisfy its declared milestone;
the final audit must cover the complete public contract.

Leave all nine `review/01-discovery` through `review/09-release-candidate`
PRs open for the user. Never merge a PR without the user's explicit approval
of that specific PR; passing CI and agent reviews are insufficient. Never
enable auto-merge or publish without explicit user authorization. After an
approved squash merge, replay only each later branch's own commits onto its
new base and retarget the next PR to main. Pin and review the resulting heads.

Old PRs #1–#5 and their CI runs describe the archived implementation at
`archive/implementation-before-review-reset` (`fc5c7ba`). They do not establish
approval or validation of the new review stack. Private visibility is
intentional during user review and does not block that review.
