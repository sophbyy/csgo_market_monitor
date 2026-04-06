from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    steam_api_key: str
    sih_extension_path: str
    profile_dir: str = "browser_profile"
    output_csv: str = "output/bot_profiles.csv"
    platform: str = "market.csgo.com"
    min_delay_seconds: float = 5.0
    max_delay_seconds: float = 9.0


def get_settings() -> Settings:
    steam_api_key = os.getenv("STEAM_API_KEY", "").strip()
    sih_extension_path = os.getenv("SIH_EXTENSION_PATH", "").strip()
    if not steam_api_key:
        raise RuntimeError("STEAM_API_KEY is required in environment.")
    return Settings(
        steam_api_key=steam_api_key,
        sih_extension_path=sih_extension_path,
    )


