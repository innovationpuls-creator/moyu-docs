# Account Domain Module

Owns account lifecycle and account authentication domain policies.

- `domain/`: entities and pure policies
- `application/`: use-case orchestration boundary
- `ports/`: interfaces for dependencies implemented outside core

The domain layer has no framework, database, cache, queue, or transport imports.
