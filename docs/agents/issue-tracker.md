# Review specifications

Review the scope and acceptance criteria in the PR description against
[protocol discovery](../discovery.md) and the public API documentation.
Record validation and review findings on the PR.

Use GitHub pull requests in `cheenulabs/pi-agent-python-sdk`.
For each review, pin the previous milestone commit and compare the proposed
branch against it. Review standards from CONTRIBUTING.md separately from
the PR's declared requirements. A PR need only satisfy its declared milestone;
the final audit must cover the complete public contract.

Follow the PR template and title convention in [AGENTS.md](../../AGENTS.md).
Merge only PRs explicitly approved by the user; passing checks do not replace
approval. Keep auto-merge off and obtain separate authorization to publish.
After an approved squash merge, replay only each dependent branch's own changes
onto its updated base and retarget the next PR to main. Validate the resulting
heads before merging them. Record test results against the commits actually
checked.
