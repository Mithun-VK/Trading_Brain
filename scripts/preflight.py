"""Production preflight check.

Exits non-zero if the configuration is not fit for the environment it claims
to be. Intended for a deploy pipeline, where a non-zero exit stops the
rollout -- unlike the startup log lines, which can scroll past unread.

    python -m scripts.preflight
"""

from __future__ import annotations

import sys

from config.settings import get_settings


def main() -> int:
    settings = get_settings()
    issues = settings.production_issues()

    print(f"APP_ENV = {settings.app_env}")
    if not settings.is_production:
        print("Not a production environment; no production checks apply.")
        return 0

    if not issues:
        print("OK: no production configuration issues found.")
        return 0

    print(f"\n{len(issues)} production configuration issue(s):\n")
    for issue in issues:
        print(f"  - {issue}")
    print("\nRefusing to certify this configuration as production-ready.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
