"""User configuration, read from ~/doit.cfg (INI format).

Every setting has a working default, so doit runs with no config file
at all. Switching the model is a one-line edit:

    [doit]
    model = ollama/mistral:7b
"""

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / "doit.cfg"


@dataclass
class Config:
    """Tunable settings for a doit run."""

    model: str = "openai/gpt-4o-mini"  # any LiteLLM model string
    temperature: float = 0.0
    max_steps: int = 1  # 1 = single-command mode (Phase 1)
    command_timeout_seconds: int = 30
    shell: str = ""  # path to the shell for running commands; "" = auto-detect


def load_config() -> Config:
    """Return the settings from ~/doit.cfg, falling back to defaults."""
    config = Config()
    parser = configparser.ConfigParser()
    if parser.read(CONFIG_PATH) and parser.has_section("doit"):
        section = parser["doit"]
        config.model = section.get("model", config.model)
        config.temperature = section.getfloat("temperature", config.temperature)
        config.max_steps = section.getint("max_steps", config.max_steps)
        config.command_timeout_seconds = section.getint(
            "command_timeout_seconds", config.command_timeout_seconds
        )
        config.shell = section.get("shell", config.shell)
    return config


def resolve_shell(config: Config) -> str:
    """Return the shell to execute commands with.

    The config value wins; otherwise use the user's login shell ($SHELL),
    and as a last resort /bin/sh.
    """
    return config.shell or os.environ.get("SHELL", "/bin/sh")
