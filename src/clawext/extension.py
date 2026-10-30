"""Extension declaration: metadata plus a registry of typed command functions."""

from __future__ import annotations

import inspect
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar, overload

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel

from . import __version__
from .config import LoadedConfig, load_config
from .context import Context
from .errors import ExtensionError, UsageError, WrongHostError
from .params import GlobalOpt, ParamSpec, describe_params, split_doc, takes_context
from .plugin import DEFAULT_PLUGIN, Plugin
from .secrets import ScopedSecrets, SecretStore
from .state import RUNS_ON_VALUES, STATE_CLASSES

Config = BaseModel
"""Base class for an extension's typed config; subclass it and give every field a default."""

F = TypeVar("F", bound=Callable[..., Any])
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class Needs:
    """External requirements verified by ``doctor``.

    Attributes:
        bins: Executables that must be on ``PATH``.
        python: Importable Python modules that must be installed.
    """

    bins: tuple[str, ...] = ()
    python: tuple[str, ...] = ()


@dataclass
class Command:
    """One registered command.

    Attributes:
        name: Command name as typed on the CLI.
        func: The wrapped function (first parameter is the context).
        help: Docstring text used for ``--help`` and the generated skill.
        destructive: Whether the command needs ``--yes`` to run.
        exit_for: Optional function mapping the result to a process exit code.
        hidden: Hide from ``--help`` (still callable).
        aliases: Extra names that run the same command (hidden from help).
        params: Parameter specs, derived from the signature, annotations and docstring.
        wants_ctx: Whether the function takes the context as first parameter.
    """

    name: str
    func: Callable[..., Any]
    help: str
    destructive: bool = False
    exit_for: Callable[[Any], int] | None = None
    hidden: bool = False
    aliases: tuple[str, ...] = ()
    params: list[ParamSpec] = field(default_factory=list)
    wants_ctx: bool = True


def make_command(
    name: str,
    func: Callable[..., Any],
    *,
    destructive: bool = False,
    exit_for: Callable[[Any], int] | None = None,
    hidden: bool = False,
    aliases: Sequence[str] = (),
) -> Command:
    """Build a :class:`Command` from a function, deriving help and parameters.

    Args:
        name: Command name.
        func: The command function.
        destructive: Require ``--yes``.
        exit_for: Map the result to an exit code.
        hidden: Hide from ``--help``.
        aliases: Extra names for the command.

    Returns:
        The command, with params taken from the signature, annotations and docstring.
    """
    summary, arg_help = split_doc(inspect.getdoc(func) or "")
    return Command(
        name,
        func,
        summary,
        destructive,
        exit_for,
        hidden,
        tuple(aliases),
        describe_params(func, arg_help),
        takes_context(func),
    )


@dataclass
class Extension:
    """A declared extension; build with :func:`extension`.

    Attributes:
        name: Extension name (lowercase, digits, ``-``).
        about: One-line description.
        plugin: Owning plugin (or the default standalone plugin).
        config: Config model class or ``None``.
        secrets: Declared secret names.
        needs: Requirements checked by ``doctor``.
        runs_on: ``local``, ``server`` or ``any``.
        state: Sync class of the extension's state.
        requires_framework: Accepted clawext version range, if any.
        skill_template: Jinja template for the generated skill (built-in when ``None``).
        global_options: Options accepted before the subcommand (``ctx.globals``).
        commands: Registered commands by name.
    """

    name: str
    about: str
    plugin: Plugin = DEFAULT_PLUGIN
    config: type[BaseModel] | None = None
    secrets: tuple[str, ...] = ()
    needs: Needs = field(default_factory=Needs)
    runs_on: str = "any"
    state: str = "host"
    requires_framework: str | None = None
    skill_template: Path | None = None
    global_options: tuple[GlobalOpt, ...] = ()
    commands: dict[str, Command] = field(default_factory=dict)

    @overload
    def command(self, func: F) -> F: ...

    @overload
    def command(
        self,
        *,
        name: str | None = None,
        destructive: bool = False,
        exit_for: Callable[[Any], int] | None = None,
        hidden: bool = False,
        aliases: Sequence[str] = (),
    ) -> Callable[[F], F]: ...

    def command(
        self,
        func: F | None = None,
        *,
        name: str | None = None,
        destructive: bool = False,
        exit_for: Callable[[Any], int] | None = None,
        hidden: bool = False,
        aliases: Sequence[str] = (),
    ) -> F | Callable[[F], F]:
        """Register a function as a command (usable bare or with options).

        Args:
            func: The function when used as ``@app.command``.
            name: Override the command name (default: function name, ``_`` to ``-``).
            destructive: Require ``--yes`` before the command runs.
            exit_for: Map the result to a process exit code (non-zero without an error).
            hidden: Hide the command from ``--help``.
            aliases: Extra names that run the same command.

        Returns:
            The function unchanged, or a decorator.
        """

        def register(target: F) -> F:
            cmd_name = name or target.__name__.replace("_", "-")
            if cmd_name in self.commands:
                raise UsageError(f"duplicate command '{cmd_name}' in extension '{self.name}'")
            self.commands[cmd_name] = make_command(
                cmd_name,
                target,
                destructive=destructive,
                exit_for=exit_for,
                hidden=hidden,
                aliases=aliases,
            )
            return target

        return register(func) if func is not None else register

    def check_host(self, environ: Mapping[str, str] | None = None) -> None:
        """Refuse to run on the wrong machine role.

        Args:
            environ: Environment to read; defaults to ``os.environ``.

        Raises:
            WrongHostError: ``runs_on`` pins another role than the current one.
        """
        if self.runs_on == "any":
            return
        role = self.plugin.role(environ)
        if role is not None and role != self.runs_on.upper():
            raise WrongHostError(
                f"'{self.name}' runs on {self.runs_on} but this machine is {role}",
                hint=f"run it on the {self.runs_on} machine (e.g. over the reverse tunnel)",
            )

    def build_context(
        self, environ: Mapping[str, str] | None = None, *, json_mode: bool = False
    ) -> Context:
        """Create the per-run context (loads config and wires scoped secrets).

        Args:
            environ: Environment to read; defaults to ``os.environ``.
            json_mode: Whether the caller asked for JSON output.

        Returns:
            A ready context.
        """
        env = dict(os.environ if environ is None else environ)
        store = SecretStore(self.plugin.home_dir(env) / "secrets.yaml")
        secrets = ScopedSecrets(store, self.secrets, self.name)
        loaded: LoadedConfig = load_config(self.config, self.plugin, self.name, secrets, env)
        return Context(
            extension=self.name,
            plugin=self.plugin,
            loaded=loaded,
            secrets=secrets,
            environ=env,
            json_mode=json_mode,
        )


def _resolve_skill(skill: str | Path, caller: Any) -> Path:
    """Resolve a skill template path: absolute as given, relative to the declaring module or above."""
    path = Path(skill)
    if path.is_absolute():
        return path
    here = Path(str(caller.f_globals.get("__file__", "."))).resolve().parent
    for base in (here, *here.parents):
        if (base / path).is_file():
            return base / path
    return path


def _coerce_needs(needs: Needs | Mapping[str, Sequence[str]] | None) -> Needs:
    if needs is None:
        return Needs()
    if isinstance(needs, Needs):
        return needs
    unknown = set(needs) - {"bins", "python"}
    if unknown:
        raise UsageError(f"unknown needs keys: {', '.join(sorted(unknown))}")
    return Needs(bins=tuple(needs.get("bins", ())), python=tuple(needs.get("python", ())))


def check_framework_range(requires: str | None, version: str = __version__) -> None:
    """Verify the running clawext satisfies an extension's declared range.

    Args:
        requires: Version specifier such as ``">=0.1,<0.2"``, or ``None`` for any.
        version: Framework version to test (defaults to the installed one).

    Raises:
        ExtensionError: The specifier is invalid or the version is outside it.
    """
    if requires is None:
        return
    try:
        spec = SpecifierSet(requires)
    except InvalidSpecifier as exc:
        raise ExtensionError(f"invalid requires_framework {requires!r}") from exc
    if not spec.contains(version, prereleases=True):
        raise ExtensionError(
            f"requires clawext {requires} but {version} is installed",
            hint="upgrade clawext or the extension",
        )


def extension(
    name: str,
    about: str,
    *,
    plugin: Plugin | None = None,
    config: type[BaseModel] | None = None,
    secrets: Sequence[str] = (),
    needs: Needs | Mapping[str, Sequence[str]] | None = None,
    runs_on: str = "any",
    state: str = "host",
    requires_framework: str | None = None,
    skill: str | Path | None = None,
    global_options: Sequence[GlobalOpt] = (),
) -> Extension:
    """Declare an extension.

    Args:
        name: Extension name (lowercase letters, digits, ``-``).
        about: One-line description (used in help and the skill).
        plugin: Owning plugin, or ``None`` for a standalone extension.
        config: Config model class (subclass of ``Config``) or ``None``.
        secrets: Secret names the extension may read (dotted keys).
        needs: Requirements checked by ``doctor``: ``bins`` and ``python``.
        runs_on: ``local``, ``server`` or ``any``.
        state: State sync class: ``host``, ``git`` or ``server-owned``.
        requires_framework: Accepted clawext version range.
        skill: Path to a Jinja ``SKILL.md.j2`` template that replaces the built-in layout.
        global_options: ``GlobalOpt`` entries accepted before the subcommand.

    Returns:
        The extension; register commands with ``@app.command``.

    Raises:
        UsageError: A declared value is invalid.
        ExtensionError: The installed clawext is outside ``requires_framework``.
    """
    if not _NAME_RE.match(name):
        raise UsageError(f"invalid extension name {name!r}: use lowercase letters, digits, '-'")
    if runs_on not in RUNS_ON_VALUES:
        raise UsageError(f"runs_on must be one of {RUNS_ON_VALUES}, got {runs_on!r}")
    if state not in STATE_CLASSES:
        raise UsageError(f"state must be one of {STATE_CLASSES}, got {state!r}")
    check_framework_range(requires_framework)
    skill_path = _resolve_skill(skill, sys._getframe(1)) if skill is not None else None
    return Extension(
        name=name,
        about=about,
        plugin=plugin or DEFAULT_PLUGIN,
        config=config,
        secrets=tuple(secrets),
        needs=_coerce_needs(needs),
        runs_on=runs_on,
        state=state,
        requires_framework=requires_framework,
        skill_template=skill_path,
        global_options=tuple(global_options),
    )
