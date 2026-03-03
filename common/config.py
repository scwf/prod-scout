"""Shared config loading helpers."""

from __future__ import annotations

import configparser
import os


def resolve_path(anchor_file: str, relative_path: str) -> str:
    """Resolve a path relative to the module file that is requesting it."""
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(anchor_file)), relative_path))


def load_ini(anchor_file: str, relative_path: str, preserve_case: bool = False) -> configparser.ConfigParser:
    """Load an INI file relative to a module file."""
    config = configparser.ConfigParser()
    if preserve_case:
        config.optionxform = str
    config.read(resolve_path(anchor_file, relative_path), encoding="utf-8")
    return config


def load_project_ini(
    anchor_file: str,
    config_name: str,
    package_depth: int,
    preserve_case: bool = False,
) -> configparser.ConfigParser:
    """Load an INI file from the project root based on the caller's package depth."""
    relative_parts = [".."] * (package_depth + 1) + [config_name]
    return load_ini(anchor_file, os.path.join(*relative_parts), preserve_case=preserve_case)
