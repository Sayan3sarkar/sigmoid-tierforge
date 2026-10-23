from logging import basicConfig


def configure_logging(level: str) -> None:
    basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
