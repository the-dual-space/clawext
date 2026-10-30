"""Exception hierarchy with stable process exit codes."""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3


class ClawextError(Exception):
    """Base class for expected, user-facing failures.

    Attributes:
        exit_code: Process exit code the CLI returns for this error.
        kind: Short machine-readable error type used in the JSON error envelope.
        hint: Optional one-line suggestion for how to fix the problem.
    """

    exit_code: int = EXIT_FAILURE
    kind: str = "error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        """Create the error.

        Args:
            message: What went wrong.
            hint: How to fix it, if there is an obvious fix.
        """
        super().__init__(message)
        self.hint = hint

    def to_dict(self) -> dict[str, object]:
        """Return the JSON error envelope body.

        Returns:
            A mapping with ``code``, ``type``, ``message`` and (if set) ``hint``.
        """
        body: dict[str, object] = {
            "code": self.exit_code,
            "type": self.kind,
            "message": str(self),
        }
        if self.hint:
            body["hint"] = self.hint
        return body


class UsageError(ClawextError):
    """The command was invoked incorrectly (bad declaration or arguments)."""

    exit_code = EXIT_USAGE
    kind = "usage"


class ConfigError(ClawextError):
    """Configuration is missing, malformed, or fails validation."""

    exit_code = EXIT_USAGE
    kind = "config"


class SecretError(ConfigError):
    """A secret could not be resolved."""

    kind = "secret"


class SecretMissingError(SecretError):
    """A declared secret has no value in the secrets file."""

    kind = "secret_missing"


class SecretNotDeclaredError(SecretError):
    """An extension asked for a secret it did not declare."""

    kind = "secret_not_declared"


class WrongHostError(ClawextError):
    """The extension must run on a different machine role."""

    exit_code = EXIT_USAGE
    kind = "wrong_host"


class UnreachableError(ClawextError):
    """A remote target could not be reached."""

    exit_code = EXIT_UNREACHABLE
    kind = "unreachable"


class ExtensionError(ClawextError):
    """An extension could not be loaded, installed, or is incompatible."""

    kind = "extension"
