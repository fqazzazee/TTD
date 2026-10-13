# Security policy — TTD

## Supported versions

Only the current `main` branch gets security fixes.

## Reporting a vulnerability

Do not open a public issue.

Use [private vulnerability reporting](https://github.com/fqazzazee/TTD/security/advisories/new),
or email fadi.qazzazee@gmail.com with the details and, if you have one, a proof of
concept.

Expect an acknowledgment within 72 hours and an assessment within a week. If a fix is
warranted, you will get the timeline and credit in the release notes unless you would
rather not be named.

## Scope

**In scope:** the game code in this repository. It uses only the Python standard library
and makes no network calls, so the realistic findings are unsafe file handling, such as
how scores or settings are saved and loaded, and terminal escape sequences reaching the
terminal from data the game reads.

**Out of scope:** anything that requires an attacker to already have the privileges the
issue would grant.
