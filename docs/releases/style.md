# Release notes style

Reviewed on 2026-09-18 against four official Pi releases. The selection covers
a compact patch, a feature release, an API migration, and a broader redesign;
it is a comparison of useful formats, not a ranking of release importance.

## What Pi does

| Release | Why it is useful | Format and emphasis |
|---|---|---|
| [v0.85.1](https://github.com/earendil-works/pi/releases/tag/v0.85.1) | Compact patch and our recorded upstream baseline | Version-only title; New Features, Added, Fixed. One highlighted capability links to documentation at the release tag. Fixes describe affected behavior, including the supported SDK/RPC boundary. |
| [v0.85.0](https://github.com/earendil-works/pi/releases/tag/v0.85.0) | Larger feature release | Three brief, bold feature highlights precede Added, Changed, Fixed. Detailed entries often include PR/issue links and contributor credit. Documentation links point to the release tag. |
| [v0.51.0](https://github.com/earendil-works/pi/releases/tag/v0.51.0) | Breaking extension API change | Breaking Changes comes first, with before/after code for the changed function signature. New Features, Added, and Fixed follow. Installation commands and RPC documentation links appear where they help users act. |
| [v0.35.0](https://github.com/earendil-works/pi/releases/tag/v0.35.0) | Hooks/tools unified into extensions | Opens with the redesign and reading links, then organizes migration by affected surface. Separates automatic migration from manual work and shows directory, import, settings, and CLI changes. Breaking Changes and Changed summarize the impact afterward. |

Pi adjusts detail to the user's work: short bullets for routine changes, code
when callers must change code, and a migration guide for a redesign. Its recent
releases use absolute links pinned to a tag; older examples above use relative
documentation links. Use the recent link style when writing a GitHub release.
Sources: [v0.85.0](https://github.com/earendil-works/pi/releases/tag/v0.85.0),
[v0.51.0](https://github.com/earendil-works/pi/releases/tag/v0.51.0),
[v0.35.0](https://github.com/earendil-works/pi/releases/tag/v0.35.0).

## Apply this to the Python SDK

The following is our editorial guidance, informed by that comparison.

- Use the GitHub release title `vX.Y.Z`; let the opening sentence explain the
  release. Describe this package as a community Python SDK for Pi.
- Lead with three to five capabilities or behavior changes that matter to SDK
  users. Give substantial highlights their own subheading, a short paragraph,
  and a separate documentation link. Use blank lines between list items so the
  rendered release has visible spacing; use a table for runtime requirements.
- Keep each paragraph and list item on one source line, including its PR links.
  Let the editor and browser wrap long lines; preserve line breaks in code blocks.
- For the first release, explain what callers can build, then show installation
  and one short, runnable example. State the separate Pi installation and
  provider setup requirements. Link to the async and streaming examples.
- Keep package and import names explicit: install `pi-agent-python-sdk`, import
  `pi_agent`. If addressing earlier source checkouts, give the old-to-new names
  and required action in a short migration note.
- State minimum runtimes and the tested Pi baseline precisely. Link to the
  [compatibility policy](../compatibility.md) for newer-version behavior and
  platform coverage; do not turn a tested baseline into a promise about every
  future version.
- Explain that Pi owns authentication, model execution, tools, and sessions;
  link to the [RPC guide](../rpc.md) for the subprocess boundary.
- Use absolute repository URLs pinned to the proposed release tag for links in
  the published body. Resolve those paths against the reviewed source before
  publication, and check the URLs again once the approved tag exists.
- Link PRs/issues beside changes when they help explain provenance; credit
  contributors for their actual changes. Keep workflow approvals, checklist
  status, and CI transcripts in the [release process](../releasing.md) or PR.

## Future updates

Start with Breaking Changes when users must act. Explain who is affected, the
replacement behavior, and the smallest before/after example that makes the
migration clear. If there is a substantial redesign, separate automatic changes
from manual migration and link to a dedicated guide.

Follow with New Features, then Added, Changed, or Fixed only when they contain
useful information. Avoid empty headings and repeating a highlighted feature
word for word in Added. Keep the full change inventory in the
[changelog](../../CHANGELOG.md); release notes should make the important changes
easy to find and use.
