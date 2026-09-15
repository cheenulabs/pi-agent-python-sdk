# Contributing

Keep the client small and reviewable. Pi owns agent behavior, credentials,
configuration, models, extensions, tools, and session storage. Preserve its
defaults unless the caller explicitly overrides them.

Use Python 3.11-compatible syntax, standard-library runtime dependencies,
explicit public methods, and typed wire dictionaries. Comments should explain
non-obvious ordering, cancellation, and compatibility decisions. Public
docstrings should describe behavior and failure conditions.

Test through public interfaces or the private subprocess seam with a fake
executable. Cover observable behavior and failures; avoid tests that merely
repeat code structure. Use synthetic data and isolated temporary directories.
Never include real credentials, conversations, provider headers, or private
configuration in fixtures, diagnostics, examples, or issue reports.

Before a pull request, run the development commands in [README.md](README.md).
Describe the concrete behavior change and relevant validation. Changes to the
supported protocol need updates to types, fixtures, documentation, and the
coverage inventory. Unknown upstream metadata must remain accessible.
