# The CLI reads its config and rate card from XDG user directories, not the repo

`jwoo` installs as a package, so a repo working copy stops being a meaningful place to
read configuration from — "the repo root" would mean either `site-packages` or a stale
checkout. Settings live in `~/.config/jwoo/config.toml`, the canonical store in the XDG
data directory, and the rate card ships *inside* the package as a default with a full-file
override at `~/.config/jwoo/rate-card.toml`. Precedence is defaults < config file <
environment variables < CLI flags.

The environment-variable names stay the existing ones (`MONGO_URI`, `ACTIVITY_DB_NAME`,
`FLUSH_INTERVAL_SECONDS`, `MOUSE_DPI`) rather than being renamed to match the TOML keys, so
the `env` block in `~/.claude/settings.json` keeps working untouched — that file currently
holds the credentials, and not having to edit it is what keeps the cutover to a
command-string change.

**Considered and rejected:** keeping the repo-root `.env` (the tool is installed, not run
from a clone); hand-editing the rate card where it ships (an edit inside `site-packages` is
destroyed by the next upgrade); a user-only rate card with no bundled default (a fresh
install would price nothing until someone wrote a card file by hand); and merging the user's
card file over the packaged one (a merge reintroduces exactly the overlap and gap questions
ADR-0004 exists to make decidable, so the override replaces the file wholesale).

**Consequences:** the package ships a default rate card, which means model pricing for new
models arrives with an upgrade rather than needing an edit. Secrets sit in a `0600` file in
a private user directory, which is a strict improvement on today's plaintext connection
string in `~/.claude/settings.json` — and since environment variables outrank the file,
injecting `MONGO_URI` from a secret manager needs no extra code.
