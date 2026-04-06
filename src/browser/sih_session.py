from __future__ import annotations

import os

from playwright.sync_api import BrowserContext, sync_playwright

from src.config import Settings


def launch_persistent_context(settings: Settings) -> BrowserContext:
    args: list[str] = []
    if settings.sih_extension_path:
        ext_path = settings.sih_extension_path
        manifest = os.path.join(ext_path, "manifest.json")
        if not os.path.isfile(manifest):
            raise FileNotFoundError(
                f"SIH extension manifest not found at {manifest!r}. "
                f"Check that SIH_EXTENSION_PATH in .env is correct "
                f"(watch out for missing spaces in 'Application Support')."
            )
        args.extend(
            [
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ]
        )

    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=settings.profile_dir,
        headless=False,
        args=args,
    )
    return context

