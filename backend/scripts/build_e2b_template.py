"""Build and publish the AutoPatch E2B template. Requires E2B_API_KEY."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from e2b import Template, default_build_logger

from app.config import settings
from app.services.e2b_template import TEMPLATE_NAME, build_autopatch_template


def main() -> None:
    if not settings.e2b_api_key:
        raise SystemExit("E2B_API_KEY is not set")
    template = build_autopatch_template()
    info = Template.build(
        template,
        TEMPLATE_NAME,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=default_build_logger(),
        api_key=settings.e2b_api_key,
    )
    print("template_alias", TEMPLATE_NAME)
    print("template_id", info.template_id)
    print("build_id", info.build_id)


if __name__ == "__main__":
    main()
