"""Parameter metadata: ``Opt``/``Arg`` markers and the ``ParamSpec`` model shared by CLI, schema and skill."""

from __future__ import annotations

import enum
import inspect
import re
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import UsageError

_SECTION_RE = re.compile(
    r"^(Args|Arguments|Returns|Raises|Yields|Attributes|Example|Examples):\s*$"
)
_ARG_RE = re.compile(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")


@dataclass(frozen=True)
class OptSpec:
    """Metadata for a parameter that becomes a ``--option``.

    Attributes:
        long: Replacement long flag (for example ``--id``); the default is derived from the name.
        shorts: Short flags such as ``-n``.
        help: Help text (defaults to the docstring ``Args:`` entry).
        choices: Allowed values (``Literal`` and ``Enum`` annotations set this automatically).
        required: The option must be given (only meaningful without a default).
        metavar: Placeholder shown in help.
        exists: For ``Path``: the path must exist.
        negatable: For ``bool``: also offer ``--no-x`` (default: only when the default is True).
        hidden: Hide from ``--help``.
    """

    long: str | None = None
    shorts: tuple[str, ...] = ()
    help: str | None = None
    choices: tuple[str, ...] | None = None
    required: bool = False
    metavar: str | None = None
    exists: bool = False
    negatable: bool | None = None
    hidden: bool = False


@dataclass(frozen=True)
class ArgSpec:
    """Metadata for a parameter that becomes a positional argument.

    Attributes:
        help: Help text (defaults to the docstring ``Args:`` entry).
        metavar: Placeholder shown in usage.
        exists: For ``Path``: the path must exist.
    """

    help: str | None = None
    metavar: str | None = None
    exists: bool = False


def Opt(
    *flags: str,
    help: str | None = None,
    choices: Sequence[str] | None = None,
    required: bool = False,
    metavar: str | None = None,
    exists: bool = False,
    negatable: bool | None = None,
    hidden: bool = False,
) -> OptSpec:
    """Mark a parameter as an option and set its flags, help and choices.

    Example: ``limit: Annotated[int, Opt("-n", help="Row limit")] = 10``.

    Args:
        *flags: Short flags (``-n``) and/or one replacement long flag (``--id``).
        help: Help text.
        choices: Allowed values.
        required: The option must be given.
        metavar: Placeholder shown in help.
        exists: For ``Path``: the path must exist.
        negatable: For ``bool``: also offer ``--no-x``.
        hidden: Hide from ``--help``.

    Returns:
        The marker to place inside ``Annotated[...]``.

    Raises:
        UsageError: A flag is malformed.
    """
    long: str | None = None
    shorts: list[str] = []
    for flag in flags:
        if flag.startswith("--") and len(flag) > 2:
            if long is not None:
                raise UsageError(f"Opt: more than one long flag ({long}, {flag})")
            long = flag
        elif re.fullmatch(r"-[A-Za-z]", flag):
            shorts.append(flag)
        else:
            raise UsageError(f"Opt: invalid flag {flag!r} (use -x or --name)")
    return OptSpec(
        long, tuple(shorts), help, tuple(choices) if choices else None, required, metavar,
        exists, negatable, hidden,
    )  # fmt: skip


def Arg(
    *,
    help: str | None = None,
    metavar: str | None = None,
    exists: bool = False,
) -> ArgSpec:
    """Mark a defaulted parameter as an optional positional instead of an option.

    Example: ``path: Annotated[str | None, Arg()] = None``.

    Args:
        help: Help text.
        metavar: Placeholder shown in usage.
        exists: For ``Path``: the path must exist.

    Returns:
        The marker to place inside ``Annotated[...]``.
    """
    return ArgSpec(help, metavar, exists)


@dataclass
class ParamSpec:
    """Everything known about one command parameter.

    Attributes:
        name: Python parameter name (the key passed to the function).
        kind: ``argument`` or ``option``.
        long: Long flag for options (``--dry-run``).
        shorts: Short flags for options.
        type_name: Readable type (``int``, ``Path``, ``list[str]``).
        base: Scalar Python type after unwrapping Optional/list.
        required: Must be supplied.
        default: Default value (``None`` when required).
        help: Help text.
        choices: Allowed values, if restricted.
        metavar: Placeholder.
        multiple: Accepts several values.
        is_flag: Boolean switch.
        negatable: Has a ``--no-`` form.
        exists: Path must exist.
        hidden: Hidden from help.
    """

    name: str
    kind: str
    long: str | None
    shorts: tuple[str, ...]
    type_name: str
    base: Any
    required: bool
    default: Any
    help: str
    choices: tuple[str, ...] | None
    metavar: str | None
    multiple: bool
    is_flag: bool
    negatable: bool
    exists: bool
    hidden: bool
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        """Return the name as shown to users (``dry-run`` for options, ``file`` for arguments)."""
        return (
            (self.long or "--" + self.name.replace("_", "-")).lstrip("-")
            if self.kind == "option"
            else self.name
        )


def type_name(hint: Any) -> str:
    """Return a short readable name for a type annotation.

    Args:
        hint: A type annotation.

    Returns:
        For example ``"int"``, ``"Path"`` or ``"list[str]"``.
    """
    if hint is inspect.Parameter.empty:
        return "str"
    if hint is type(None):
        return "None"
    origin = typing.get_origin(hint)
    if origin is None:
        return str(getattr(hint, "__name__", hint))
    if origin is typing.Literal:
        return "|".join(str(a) for a in typing.get_args(hint))
    if origin in (typing.Union, types.UnionType):
        return " | ".join(type_name(a) for a in typing.get_args(hint))
    args = ", ".join(type_name(a) for a in typing.get_args(hint))
    return f"{getattr(origin, '__name__', str(origin))}[{args}]"


def split_doc(doc: str) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into its description and per-argument help.

    Args:
        doc: The cleaned docstring (``inspect.getdoc``).

    Returns:
        The text before the first section (``Args:``, ``Returns:`` ...), and a mapping of
        argument name to its help line(s) from the ``Args:`` section.
    """
    lines = doc.splitlines()
    head: list[str] = []
    args: dict[str, str] = {}
    section: str | None = None
    current: str | None = None
    for line in lines:
        match = _SECTION_RE.match(line.strip()) if not line.startswith(" ") else None
        if match:
            section = match.group(1)
            current = None
            continue
        if section is None:
            head.append(line)
        elif section in ("Args", "Arguments") and line.strip():
            entry = _ARG_RE.match(line.strip())
            indented = line.startswith((" ", "\t"))
            if (
                entry
                and (not indented or len(line) - len(line.lstrip()) <= 4)
                and (current is None or len(line) - len(line.lstrip()) <= 4)
            ):
                current = entry.group(1)
                args[current] = entry.group(2).strip()
            elif current:
                args[current] = (args[current] + " " + line.strip()).strip()
    return "\n".join(head).strip(), args


def takes_context(func: Callable[..., Any]) -> bool:
    """Return whether the first parameter of ``func`` is the command context.

    A first parameter named ``ctx``/``context`` or annotated ``Context`` is the context;
    anything else is the first command parameter (commands may omit the context).

    Args:
        func: The command function.

    Returns:
        ``True`` when the function expects the context first.
    """
    params = list(inspect.signature(func).parameters.values())
    if not params:
        return False
    first = params[0]
    if first.name in ("ctx", "context"):
        return True
    try:
        hint = typing.get_type_hints(func).get(first.name)
    except Exception:
        return False
    return getattr(hint, "__name__", "") == "Context"


def _unwrap(hint: Any) -> tuple[Any, list[Any]]:
    """Strip ``Annotated`` and return ``(base, metadata)``."""
    meta: list[Any] = []
    while typing.get_origin(hint) is typing.Annotated:
        args = typing.get_args(hint)
        hint = args[0]
        meta.extend(args[1:])
    return hint, meta


def _optional(hint: Any) -> Any:
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        rest = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(rest) == 1:
            return rest[0]
    return hint


def describe_params(
    func: Callable[..., Any], doc_help: dict[str, str] | None = None
) -> list[ParamSpec]:
    """Describe the command parameters of ``func`` (the context is skipped).

    Rules: a parameter without default is a positional argument (or a required option when
    marked ``Opt``); with a default it is an option (or an optional positional when marked
    ``Arg``). ``bool`` is a flag, ``list[T]`` repeats, ``Literal``/``Enum`` become choices.

    Args:
        func: The command function.
        doc_help: Per-argument help from the docstring.

    Returns:
        One spec per parameter, in signature order.

    Raises:
        UsageError: A parameter combines incompatible markers.
    """
    doc_help = doc_help or {}
    sig = inspect.signature(func)
    hints = typing.get_type_hints(func, include_extras=True)
    params = list(sig.parameters.values())
    if takes_context(func):
        params = params[1:]
    specs: list[ParamSpec] = []
    for p in params:
        hint, meta = _unwrap(hints.get(p.name, str))
        opt = next((m for m in meta if isinstance(m, OptSpec)), None)
        arg = next((m for m in meta if isinstance(m, ArgSpec)), None)
        if opt and arg:
            raise UsageError(f"parameter '{p.name}' is marked both Opt and Arg")
        hint = _optional(hint)
        multiple = typing.get_origin(hint) in (list, tuple)
        base = typing.get_args(hint)[0] if multiple and typing.get_args(hint) else hint
        base = _optional(base) if multiple else base
        choices: tuple[str, ...] | None = opt.choices if opt else None
        if typing.get_origin(base) is typing.Literal:
            choices = tuple(str(a) for a in typing.get_args(base))
            base = str
        elif isinstance(base, type) and issubclass(base, enum.Enum):
            choices = tuple(str(m.value) for m in base)
            base = str
        has_default = p.default is not inspect.Parameter.empty
        is_flag = base is bool and not multiple
        positional = (arg is not None or (not has_default and opt is None)) and not is_flag
        kind = "argument" if positional else "option"
        required = (
            (not has_default)
            if kind == "argument"
            else bool(opt and opt.required and not has_default)
        )
        default = p.default if has_default else None
        help_text = (opt.help if opt else arg.help if arg else None) or doc_help.get(p.name, "")
        specs.append(
            ParamSpec(
                name=p.name,
                kind=kind,
                long=(opt.long if opt and opt.long else f"--{p.name.replace('_', '-')}")
                if kind == "option"
                else None,
                shorts=opt.shorts if opt else (),
                type_name=type_name(
                    hints.get(p.name, str) if not meta else _unwrap(hints[p.name])[0]
                ),
                base=base,
                required=required,
                default=default,
                help=help_text,
                choices=choices,
                metavar=(opt.metavar if opt else arg.metavar if arg else None),
                multiple=multiple,
                is_flag=is_flag,
                negatable=is_flag
                and (
                    (opt.negatable if opt and opt.negatable is not None else False)
                    or default is True
                ),
                exists=bool((opt and opt.exists) or (arg and arg.exists)),
                hidden=bool(opt and opt.hidden),
            )
        )
    return specs


def scalar_click_type(spec: ParamSpec) -> Any:
    """Return the Click type for a spec's scalar type.

    Args:
        spec: Parameter spec.

    Returns:
        A ``click.ParamType``.
    """
    import click

    if spec.choices:
        return click.Choice(list(spec.choices))
    if spec.base is int:
        return click.INT
    if spec.base is float:
        return click.FLOAT
    if spec.base is Path:
        return click.Path(path_type=Path, exists=spec.exists)
    return click.STRING
