# Core Domain

`app_core` contains framework-independent domain and application code.

## Account module

The account module owns account lifecycle and password policy domain rules. Its
`domain/` package does not import framework or infrastructure code. Its
`application/` package is reserved for use cases, and `ports/` contains
interfaces implemented by infrastructure adapters.
