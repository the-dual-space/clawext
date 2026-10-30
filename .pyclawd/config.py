"""clawext's pyclawd config — drives `pyclawd test/lint/typecheck/...` for this repo."""

from pyclawd import DoctorConfig, Project, QualityConfig, TestConfig

project = Project(
    name="clawext",
    conda_env=None,
    root_markers=["pyproject.toml"],
    # The pyclawd this config was built on. `pyclawd doctor` WARNs if the
    # running pyclawd has drifted to a different minor (migration may be needed).
    pyclawd_version="0.1.1",
    # Default directory `pyclawd ls` lists (the code/source root).
    src_dir="src",
    quality=QualityConfig(
        lint_cmd=["ruff", "check"],
        lint_fix_cmd=["ruff", "check", "--fix"],
        format_cmd=["ruff", "format"],
        format_check_cmd=["ruff", "format", "--check", "--quiet"],
        typecheck_cmd=["mypy"],
        check_sequence=["format-check", "lint", "typecheck", "descriptions", "test"],
    ),
    test=TestConfig(
        tests_dir="tests/",
        classname_prefix="tests.",
        integration_files=[],
        markers={
            "fast": "not slow and not integration and not golden and not benchmark",
            "default": "not slow and not golden and not benchmark",
            "all": "not golden and not benchmark",
        },
    ),
    doctor=DoctorConfig(
        core_deps=[],
        dev_deps=["pytest", "pytest-xdist", "pytest-cov"],
        tool_files=[],
        binaries=[
            ("ruff", "pip install ruff"),
            ("mypy", "pip install mypy"),
        ],
    ),
)
