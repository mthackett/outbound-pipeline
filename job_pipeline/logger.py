import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Any, Dict

# Cache configuration check to remain lightweight
_LAST_CONFIG_CHECK_TIME: float = 0.0
_CONFIG_CHECK_INTERVAL: float = 1.0  # check disk at most once per second
_CACHED_LOGGING_ENABLED: Optional[bool] = None
_DEFAULT_CONFIG_PATH = "pipeline_config.json"


def _read_config_logging_flag() -> bool:
    """Reads the logging toggle from pipeline_config.json or environment variables."""
    # 1. Environment variable override takes highest precedence
    env_override = os.environ.get("ENABLE_CLI_LOGGING", os.environ.get("CLI_LOGGING"))
    if env_override is not None:
        return env_override.strip().lower() in ("1", "true", "yes", "on", "enabled")

    # 2. Check config file
    config_path = Path(os.environ.get("PIPELINE_CONFIG_PATH", _DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        return True  # default to enabled if config file doesn't exist yet

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            val = data.get("enable_cli_logging", data.get("cli_logging"))
            if val is not None:
                return bool(val)
        return True
    except Exception:
        return True


def is_logging_enabled(force_refresh: bool = False) -> bool:
    """Returns whether CLI logging is currently enabled, with lightweight caching."""
    global _LAST_CONFIG_CHECK_TIME, _CACHED_LOGGING_ENABLED
    now = time.time()
    if force_refresh or _CACHED_LOGGING_ENABLED is None or (now - _LAST_CONFIG_CHECK_TIME > _CONFIG_CHECK_INTERVAL):
        _CACHED_LOGGING_ENABLED = _read_config_logging_flag()
        _LAST_CONFIG_CHECK_TIME = now
    return _CACHED_LOGGING_ENABLED


def set_logging_enabled(enabled: bool) -> None:
    """Explicitly updates the in-memory logging state and flushes cache."""
    global _CACHED_LOGGING_ENABLED, _LAST_CONFIG_CHECK_TIME
    _CACHED_LOGGING_ENABLED = bool(enabled)
    _LAST_CONFIG_CHECK_TIME = time.time()


def log_cli(tag: str, message: str, level: str = "INFO") -> None:
    """
    Lightweight CLI printer.
    Outputs formatted timestamps and tags to stdout with immediate flush.
    """
    if not is_logging_enabled():
        return

    now_str = datetime.now().strftime("%H:%M:%S")
    clean_tag = tag.strip().upper()
    prefix = f"[{now_str}] [{clean_tag}]"
    
    # Send cleanly to stdout and flush so logs appear immediately before blocking I/O
    try:
        print(f"{prefix} {message}", file=sys.stdout)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        safe_message = message.encode(enc, errors="replace").decode(enc)
        print(f"{prefix} {safe_message}", file=sys.stdout)
    try:
        sys.stdout.flush()
    except Exception:
        pass


@contextmanager
def log_timed_action(action_name: str, tag: str = "ACTION"):
    """
    Context manager that logs the start and completion (with elapsed time) of an action.
    """
    if not is_logging_enabled():
        yield
        return

    start_time = time.time()
    log_cli(tag, f"⏳ {action_name}...")
    try:
        yield
        elapsed = time.time() - start_time
        log_cli(tag, f"✅ {action_name} completed ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.time() - start_time
        log_cli(tag, f"❌ {action_name} failed after {elapsed:.2f}s: {e}", level="ERROR")
        raise


def log_startup(message: str) -> None:
    log_cli("STARTUP", message)


def log_config(message: str) -> None:
    log_cli("CONFIG", message)


def log_auth(message: str) -> None:
    log_cli("AUTH", message)


def log_sheets(message: str) -> None:
    log_cli("SHEETS", message)


def log_drive(message: str) -> None:
    log_cli("DRIVE", message)


def log_llm(message: str) -> None:
    log_cli("LLM", message)


def log_crm(message: str) -> None:
    log_cli("CRM", message)


def log_action(message: str) -> None:
    log_cli("ACTION", message)


def log_info(message: str) -> None:
    log_cli("INFO", message)


def log_warn(message: str) -> None:
    log_cli("WARN", message, level="WARN")


def log_error(message: str) -> None:
    log_cli("ERROR", message, level="ERROR")


def log_success(message: str) -> None:
    log_cli("SUCCESS", message)


def log_telemetry(message: str) -> None:
    log_cli("TELEMETRY", message)

