# Review and merge policy

- Before creating or updating a PR, read `.github/pull_request_template.md`
  when it is present. Use a `type(scope): concise description` title and fill
  its Overview, Files changed and why, and Validation sections with the final
  scope and actual check results.
- Prepare focused PRs and leave them open for the user's review.
- Merge only after the user explicitly approves the specific PR. Engineering
  reviews and passing CI do not substitute for that approval. Keep auto-merge off.
- Use squash merging for an approved PR. Before merging the next stacked PR,
  restack its remaining commits onto the updated base and rerun its checks.
- Publishing or creating a release requires explicit user approval after the
  publishing setup and release candidate are ready for review.
- Preserve unrelated local edits. Follow CONTRIBUTING.md for code and validation
  conventions once the foundation PR introduces it.
