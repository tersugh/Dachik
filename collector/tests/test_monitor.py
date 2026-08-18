import logging
from pathlib import Path

from collector.monitor import LOGGER, configure_logging


def test_diagnostic_log_is_private_and_writable(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "collector.log"
    LOGGER.disabled = True

    configure_logging(log_path)
    LOGGER.info("Collector lifecycle test")
    for handler in LOGGER.handlers:
        handler.flush()

    assert log_path.stat().st_mode & 0o777 == 0o600
    assert LOGGER.disabled is False
    assert "Collector lifecycle test" in log_path.read_text()
    for handler in LOGGER.handlers:
        handler.close()
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.NOTSET)
