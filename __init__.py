"""Source-application API layer.

Only official/authorized APIs are used.  ``create_provider`` returns the
simulated provider in TEST_MODE and the configurable OfficialAppProvider
otherwise.
"""
from __future__ import annotations

from config import CONFIG
from app_api.provider import CourseProvider


def create_provider() -> CourseProvider:
    if CONFIG.test_mode:
        from app_api.courses import TestModeProvider

        return TestModeProvider()
    from app_api.official_provider import OfficialAppProvider

    return OfficialAppProvider()
