from __future__ import annotations

import argparse
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional

from src.browser.platform_scraper import (
    AvanMarketScraper,
    LisSkinsScraper,
    MarketCsgoScraper,
)
from src.browser.sih_inventory_reader import SihInventoryReader
from src.browser.sih_session import launch_persistent_context
from src.config import get_settings
from src.patterns import detect_name_pattern
from src.pipeline.evaluator import ProfileData, evaluate_profile
from src.pipeline.exporter import write_csv_row
from src.rate_limiter import DomainConfig, RateLimiter
from src.steam.client import SteamApiClient
from src.steam.inventory_value import calculate_inventory_value
from src.storage.cache import FileCache
from src.discovery.batch_prefilter import PrefilterResult, batch_prefilter
from src.discovery.friend_crawler import FriendCrawler
from src.discovery.group_crawler import GroupCrawler, GroupMember
from src.storage.profile_cache import ProfileCache

logger = logging.getLogger(__name__)


_PROFILE_URL_PATTERN = re.compile(
    r"https?://steamcommunity\.com/(?P<type>id|profiles)/(?P<identifier>[^/?\s]+)",
)


def parse_profile_url(url: str) -> tuple[str, str]:
    """Parse a Steam profile URL into (url_type, identifier).

    Returns:
        A tuple of ``("vanity", vanity_name)`` or ``("steamid64", steamid)``.

    Raises:
        ValueError: If the URL doesn't match expected Steam profile formats.
    """
    match = _PROFILE_URL_PATTERN.search(url)
    if not match:
        raise ValueError(f"Unrecognised Steam profile URL: {url}")

    kind = match.group("type")
    identifier = match.group("identifier")

    if kind == "profiles":
        return ("steamid64", identifier)
    return ("vanity", identifier)


def compute_total_playtime_hours(owned_games_response: dict) -> Optional[float]:
    """Sum ``playtime_forever`` across all games and convert minutes to hours.

    Returns ``None`` when the response contains no game list (e.g. private
    profile or empty library).
    """
    inner = owned_games_response.get("response", {})
    games = inner.get("games")
    if not games:
        return None
    total_minutes = sum(game.get("playtime_forever", 0) for game in games)
    return round(total_minutes / 60.0, 2)


def enrich_profile(
    client: SteamApiClient,
    profile_url: str,
    source_platform: str,
    profile_cache: Optional[ProfileCache] = None,
    price_cache: Optional[FileCache] = None,
    sih_reader: Optional[SihInventoryReader] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> Optional[ProfileData]:
    """Resolve all Steam API data for a single profile URL.

    Returns a fully-populated ``ProfileData`` or ``None`` if an
    unrecoverable error occurs (the profile is skipped).
    """

    # 1. Parse the URL to determine vanity vs steamid64 ----------------------
    try:
        url_type, identifier = parse_profile_url(profile_url)
    except ValueError:
        logger.warning("Skipping unparseable URL: %s", profile_url)
        return None

    # 2. Resolve vanity name to steamid64 if necessary -----------------------
    steam_id: str
    if url_type == "vanity":
        # Check cache first
        if profile_cache is not None:
            cached_id = profile_cache.get_steamid(identifier)
            if cached_id:
                steam_id = cached_id
                logger.debug("Resolved vanity '%s' from cache: %s", identifier, steam_id)
            else:
                cached_id = None
        else:
            cached_id = None

        if url_type == "vanity" and not cached_id:
            try:
                vanity_resp = client.resolve_vanity_url(identifier)
                inner = vanity_resp.get("response", {})
                if inner.get("success") != 1:
                    logger.warning(
                        "Vanity URL resolution failed for '%s' (success=%s). Skipping.",
                        identifier,
                        inner.get("success"),
                    )
                    return None
                steam_id = inner["steamid"]
                if profile_cache is not None:
                    profile_cache.set_steamid(identifier, steam_id)
            except Exception:
                logger.exception("API error resolving vanity URL '%s'. Skipping.", identifier)
                return None
    else:
        steam_id = identifier

    # Skip already-checked profiles
    if profile_cache is not None and profile_cache.is_checked(steam_id):
        logger.info("Profile %s already checked, skipping.", steam_id)
        return None

    # 3. Fetch player summary (nickname, last_logoff, visibility) ------------
    nickname = ""
    last_logoff: Optional[int] = None
    try:
        summary_resp = client.get_player_summaries([steam_id])
        players = summary_resp.get("response", {}).get("players", [])
        if players:
            player = players[0]
            nickname = player.get("personaname", "")
            last_logoff = player.get("lastlogoff")
            visibility = player.get("communityvisibilitystate", 1)
            if visibility != 3:
                logger.info(
                    "Profile %s (%s) is not public (visibility=%s). "
                    "Some data may be unavailable.",
                    steam_id,
                    nickname,
                    visibility,
                )
        else:
            logger.warning("No player data returned for %s. Skipping.", steam_id)
            return None
    except Exception:
        logger.exception("API error fetching player summary for %s. Skipping.", steam_id)
        return None

    # 4. Fetch VAC ban status ------------------------------------------------
    vac_banned = False
    try:
        bans_resp = client.get_player_bans([steam_id])
        ban_players = bans_resp.get("players", [])
        if ban_players:
            vac_banned = ban_players[0].get("VACBanned", False)
    except Exception:
        logger.exception("API error fetching bans for %s. Defaulting vac_banned=False.", steam_id)

    # 5. Fetch Steam level ---------------------------------------------------
    steam_level = 0
    try:
        level_resp = client.get_steam_level(steam_id)
        steam_level = level_resp.get("response", {}).get("player_level", 0)
    except Exception:
        logger.exception("API error fetching level for %s. Defaulting level=0.", steam_id)

    # 6. Fetch owned games / total playtime ----------------------------------
    total_playtime_hours: Optional[float] = None
    try:
        games_resp = client.get_owned_games(steam_id)
        total_playtime_hours = compute_total_playtime_hours(games_resp)
    except Exception:
        logger.exception("API error fetching owned games for %s. Playtime unknown.", steam_id)

    # 7. Fetch inventory value ------------------------------------------------
    inventory_value_usd: Optional[float] = None
    try:
        if sih_reader is not None:
            sih_result = sih_reader.read_value(steam_id)
            if sih_result.value_usd is not None:
                inventory_value_usd = sih_result.value_usd
                logger.info("  SIH inventory value for %s: $%.2f", steam_id, inventory_value_usd)
            else:
                logger.debug("  SIH failed (%s) for %s, falling back to API", sih_result.source, steam_id)
                inventory_value_usd = calculate_inventory_value(
                    client.session, steam_id, cache=price_cache,
                    rate_limiter=rate_limiter,
                )
        else:
            inventory_value_usd = calculate_inventory_value(
                client.session, steam_id, cache=price_cache,
                rate_limiter=rate_limiter,
            )
        if inventory_value_usd is not None:
            logger.info("  Inventory value for %s: $%.2f", steam_id, inventory_value_usd)
        else:
            logger.info("  Inventory inaccessible for %s", steam_id)
    except Exception:
        logger.exception("Error calculating inventory value for %s", steam_id)

    # 8. Detect name pattern -------------------------------------------------
    vanity_for_pattern = identifier if url_type == "vanity" else nickname
    pattern_result = detect_name_pattern(vanity_for_pattern)

    # 9. Mark profile as checked ---------------------------------------------
    if profile_cache is not None:
        profile_cache.mark_checked(steam_id)

    # 10. Build ProfileData --------------------------------------------------
    return ProfileData(
        steam_id=steam_id,
        profile_url=profile_url,
        nickname=nickname,
        steam_level=steam_level,
        vac_banned=vac_banned,
        last_logoff=last_logoff,
        total_playtime_hours=total_playtime_hours,
        inventory_value_usd=inventory_value_usd,
        source_platform=source_platform,
        name_pattern_match=pattern_result.pattern_type if pattern_result.matches else "",
        name_pattern_confidence=pattern_result.confidence,
    )


def enrich_from_prefilter(
    client: SteamApiClient,
    result: PrefilterResult,
    source_platform: str,
    profile_cache: Optional[ProfileCache] = None,
    price_cache: Optional[FileCache] = None,
    sih_reader: Optional[SihInventoryReader] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> Optional[ProfileData]:
    """Enrich a profile that already passed batch pre-filtering.

    Skips summary and bans API calls (already done in pre-filter).
    Only fetches: level, owned games, inventory value, name pattern.
    """
    steam_id = result.steamid64

    # Fetch Steam level
    steam_level = 0
    try:
        level_resp = client.get_steam_level(steam_id)
        steam_level = level_resp.get("response", {}).get("player_level", 0)
    except Exception:
        logger.exception("API error fetching level for %s. Defaulting level=0.", steam_id)

    # Fetch owned games / total playtime
    total_playtime_hours: Optional[float] = None
    try:
        games_resp = client.get_owned_games(steam_id)
        total_playtime_hours = compute_total_playtime_hours(games_resp)
    except Exception:
        logger.exception("API error fetching owned games for %s. Playtime unknown.", steam_id)

    # Fetch inventory value
    inventory_value_usd: Optional[float] = None
    try:
        if sih_reader is not None:
            sih_result = sih_reader.read_value(steam_id)
            if sih_result.value_usd is not None:
                inventory_value_usd = sih_result.value_usd
                logger.info("  SIH inventory value for %s: $%.2f", steam_id, inventory_value_usd)
            else:
                logger.debug("  SIH failed (%s) for %s, falling back to API", sih_result.source, steam_id)
                inventory_value_usd = calculate_inventory_value(
                    client.session, steam_id, cache=price_cache,
                    rate_limiter=rate_limiter,
                )
        else:
            inventory_value_usd = calculate_inventory_value(
                client.session, steam_id, cache=price_cache,
                rate_limiter=rate_limiter,
            )
        if inventory_value_usd is not None:
            logger.info("  Inventory value for %s: $%.2f", steam_id, inventory_value_usd)
        else:
            logger.info("  Inventory inaccessible for %s", steam_id)
    except Exception:
        logger.exception("Error calculating inventory value for %s", steam_id)

    # Detect name pattern (use nickname from pre-filter)
    pattern_result = detect_name_pattern(result.nickname)

    # Mark profile as checked
    if profile_cache is not None:
        profile_cache.mark_checked(steam_id)

    return ProfileData(
        steam_id=steam_id,
        profile_url=result.profile_url,
        nickname=result.nickname,
        steam_level=steam_level,
        vac_banned=result.vac_banned,
        last_logoff=result.last_logoff,
        total_playtime_hours=total_playtime_hours,
        inventory_value_usd=inventory_value_usd,
        source_platform=source_platform,
        name_pattern_match=pattern_result.pattern_type if pattern_result.matches else "",
        name_pattern_confidence=pattern_result.confidence,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CS:GO Market Monitor - Steam bot account detection pipeline",
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        default=None,
        help=(
            "One or more Steam profile URLs to process directly, "
            "bypassing the platform scraper. "
            "Example: --urls https://steamcommunity.com/id/maraantonov"
        ),
    )
    parser.add_argument(
        "--platform",
        choices=["market.csgo.com", "lis-skins.com", "avan.market"],
        default="market.csgo.com",
        help="Trading platform to scrape (default: market.csgo.com)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Discovery mode: open the platform in a browser, wait for you "
            "to interact, then report any Steam profile URLs found on the page. "
            "Useful for inspecting what the site actually exposes."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum number of pages to scrape (default: 5)",
    )
    parser.add_argument(
        "--group",
        nargs="+",
        default=None,
        help=(
            "One or more Steam group names or URLs to crawl for member profiles. "
            "Example: --group market_csgo_com "
            "or --group https://steamcommunity.com/groups/market_csgo_com"
        ),
    )
    parser.add_argument(
        "--group-max-pages",
        type=int,
        default=None,
        help="Maximum number of member list pages to crawl per group (default: all)",
    )
    parser.add_argument(
        "--crawl-friends",
        nargs="+",
        default=None,
        metavar="STEAMID64",
        help=(
            "One or more seed SteamID64s to BFS-crawl friend networks. "
            "Discovers bot accounts that share friend connections. "
            "Example: --crawl-friends 76561198000000001"
        ),
    )
    parser.add_argument(
        "--crawl-depth",
        type=int,
        default=2,
        help="Maximum BFS depth for friend crawling (default: 2)",
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help=(
            "Search Steam Community for profiles matching Russian name patterns. "
            "Requires a browser session (opens Chromium)."
        ),
    )
    parser.add_argument(
        "--search-queries",
        type=int,
        default=20,
        help="Number of search queries to run in --search mode (default: 20)",
    )
    return parser.parse_args()


def _process_group(
    args: argparse.Namespace,
    client: SteamApiClient,
    settings,
    profile_cache: ProfileCache,
    price_cache: FileCache,
    sih_reader: Optional[SihInventoryReader] = None,
    limiter: RateLimiter | None = None,
) -> tuple[int, int]:
    """Crawl Steam group(s) and process members through the pipeline.

    Returns (processed_count, candidate_count).
    """
    crawler = GroupCrawler(
        client.session,
        delay_seconds=2.0,
        max_pages=args.group_max_pages,
        rate_limiter=limiter,
    )
    processed = 0
    candidates = 0

    for group_id in args.group:
        group_name = crawler.parse_group_identifier(group_id)
        start_page = profile_cache.get_group_last_page(group_name) + 1
        logger.info("Crawling group '%s' starting from page %d", group_name, start_page)

        page_num = start_page
        for member_page in crawler.crawl(group_id, start_page=start_page):
            logger.info(
                "Pre-filtering %d members from page %d...",
                len(member_page), page_num,
            )

            results = batch_prefilter(
                client, member_page, profile_cache=profile_cache
            )

            passed = [r for r in results if r.passed]
            logger.info(
                "  %d/%d passed pre-filter. Enriching...",
                len(passed), len(results),
            )

            for result in passed:
                profile = enrich_from_prefilter(
                    client, result, group_name,
                    profile_cache=profile_cache,
                    price_cache=price_cache,
                    sih_reader=sih_reader,
                    rate_limiter=limiter,
                )
                if profile is None:
                    continue

                evaluation = evaluate_profile(profile)
                processed += 1

                logger.info(
                    "  -> %s | level=%d vac=%s playtime=%s inv=$%s | candidate=%s%s",
                    profile.nickname,
                    profile.steam_level,
                    profile.vac_banned,
                    profile.total_playtime_hours,
                    profile.inventory_value_usd,
                    evaluation.is_candidate,
                    f" (rejected: {', '.join(evaluation.reasons)})" if evaluation.reasons else "",
                )

                if evaluation.is_candidate:
                    collected_at = datetime.now(tz=timezone.utc).isoformat()
                    write_csv_row(settings.output_csv, profile, evaluation, collected_at)
                    candidates += 1

                # Rate-limit between profiles
                if limiter is not None:
                    limiter.wait("profile")
                else:
                    time.sleep(random.uniform(settings.min_delay_seconds, settings.max_delay_seconds))

            # Save progress after each page
            profile_cache.set_group_last_page(group_name, page_num)
            page_num += 1

    return processed, candidates


def _process_friends(
    args: argparse.Namespace,
    client: SteamApiClient,
    settings,
    profile_cache: ProfileCache,
    price_cache: FileCache,
    sih_reader: Optional[SihInventoryReader] = None,
    limiter: RateLimiter | None = None,
) -> tuple[int, int]:
    """BFS-crawl friend networks and process discovered profiles.

    Returns (processed_count, candidate_count).
    """
    crawler = FriendCrawler(
        client,
        max_depth=args.crawl_depth,
        delay_seconds=1.0,
    )
    processed = 0
    candidates = 0

    logger.info(
        "Friend crawling from %d seed(s), max depth %d",
        len(args.crawl_friends), args.crawl_depth,
    )

    for member_batch in crawler.crawl(args.crawl_friends, profile_cache=profile_cache):
        logger.info("Pre-filtering %d discovered profiles...", len(member_batch))

        results = batch_prefilter(client, member_batch, profile_cache=profile_cache)
        passed = [r for r in results if r.passed]
        logger.info("  %d/%d passed pre-filter. Enriching...", len(passed), len(results))

        for result in passed:
            profile = enrich_from_prefilter(
                client, result, "friend_network",
                profile_cache=profile_cache,
                price_cache=price_cache,
                sih_reader=sih_reader,
                rate_limiter=limiter,
            )
            if profile is None:
                continue

            evaluation = evaluate_profile(profile)
            processed += 1

            logger.info(
                "  -> %s | level=%d vac=%s playtime=%s inv=$%s | candidate=%s%s",
                profile.nickname,
                profile.steam_level,
                profile.vac_banned,
                profile.total_playtime_hours,
                profile.inventory_value_usd,
                evaluation.is_candidate,
                f" (rejected: {', '.join(evaluation.reasons)})" if evaluation.reasons else "",
            )

            if evaluation.is_candidate:
                collected_at = datetime.now(tz=timezone.utc).isoformat()
                write_csv_row(settings.output_csv, profile, evaluation, collected_at)
                candidates += 1

            if limiter is not None:
                limiter.wait("profile")
            else:
                time.sleep(random.uniform(settings.min_delay_seconds, settings.max_delay_seconds))

    return processed, candidates


def _process_search(
    args: argparse.Namespace,
    client: SteamApiClient,
    settings,
    profile_cache: ProfileCache,
    price_cache: FileCache,
    sih_reader: Optional[SihInventoryReader] = None,
    limiter: RateLimiter | None = None,
    browser_context=None,
) -> tuple[int, int]:
    """Search Steam Community and process discovered profiles."""
    from src.discovery.community_search import CommunitySearcher

    owns_context = browser_context is None
    context = browser_context or launch_persistent_context(settings)
    page = context.new_page()
    searcher = CommunitySearcher(page, delay_seconds=5.0)

    processed = 0
    candidates = 0

    for member_batch in searcher.search(max_queries=args.search_queries):
        # Separate members with steamid64 from those needing vanity resolution
        resolved_batch: list[GroupMember] = []
        for member in member_batch:
            if member.steamid64:
                resolved_batch.append(member)
            else:
                # Extract vanity from URL and resolve
                vanity = member.profile_url.rstrip("/").split("/")[-1]
                cached_id = profile_cache.get_steamid(vanity) if profile_cache else None
                if cached_id:
                    resolved_batch.append(GroupMember(
                        steamid64=cached_id,
                        profile_url=member.profile_url,
                    ))
                else:
                    try:
                        resp = client.resolve_vanity_url(vanity)
                        inner = resp.get("response", {})
                        if inner.get("success") == 1:
                            sid = inner["steamid"]
                            if profile_cache:
                                profile_cache.set_steamid(vanity, sid)
                            resolved_batch.append(GroupMember(
                                steamid64=sid,
                                profile_url=member.profile_url,
                            ))
                    except Exception:
                        logger.debug("Failed to resolve vanity '%s'", vanity)

        if not resolved_batch:
            continue

        results = batch_prefilter(client, resolved_batch, profile_cache=profile_cache)
        passed = [r for r in results if r.passed]

        for result in passed:
            profile = enrich_from_prefilter(
                client, result, "community_search",
                profile_cache=profile_cache,
                price_cache=price_cache,
                sih_reader=sih_reader,
                rate_limiter=limiter,
            )
            if profile is None:
                continue

            evaluation = evaluate_profile(profile)
            processed += 1

            logger.info(
                "  -> %s | level=%d vac=%s playtime=%s inv=$%s | candidate=%s%s",
                profile.nickname,
                profile.steam_level,
                profile.vac_banned,
                profile.total_playtime_hours,
                profile.inventory_value_usd,
                evaluation.is_candidate,
                f" (rejected: {', '.join(evaluation.reasons)})" if evaluation.reasons else "",
            )

            if evaluation.is_candidate:
                collected_at = datetime.now(tz=timezone.utc).isoformat()
                write_csv_row(settings.output_csv, profile, evaluation, collected_at)
                candidates += 1

            if limiter is not None:
                limiter.wait("profile")
            else:
                time.sleep(random.uniform(settings.min_delay_seconds, settings.max_delay_seconds))

    if owns_context:
        context.close()
    return processed, candidates


def main() -> None:
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
    )
    file_handler = logging.FileHandler("app.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(file_handler)

    args = parse_args()
    settings = get_settings()
    limiter = RateLimiter()
    client = SteamApiClient(settings.steam_api_key, rate_limiter=limiter)
    profile_cache = ProfileCache()
    price_cache = FileCache(".cache/prices.json")
    sih_reader: Optional[SihInventoryReader] = None
    sih_context: Optional[object] = None  # browser context for SIH

    # Launch SIH browser context if extension is configured.
    # This is used across all discovery modes for inventory valuation.
    if settings.sih_extension_path:
        logger.info("Launching browser with SIH extension for inventory valuation...")
        sih_context = launch_persistent_context(settings)
        sih_page = sih_context.new_page()
        sih_reader = SihInventoryReader(sih_page)

    if args.group:
        # Group crawling mode: crawl Steam group member lists
        processed, candidates = _process_group(
            args, client, settings, profile_cache, price_cache,
            sih_reader=sih_reader,
            limiter=limiter,
        )
        logger.info(
            "Done. Processed %d profile(s), %d candidate(s) written to %s.",
            processed, candidates, settings.output_csv,
        )
        if sih_context is not None:
            sih_context.close()
        client.session.close()
        return

    if args.crawl_friends:
        processed, candidates = _process_friends(
            args, client, settings, profile_cache, price_cache,
            sih_reader=sih_reader,
            limiter=limiter,
        )
        logger.info(
            "Done. Processed %d profile(s), %d candidate(s) written to %s.",
            processed, candidates, settings.output_csv,
        )
        if sih_context is not None:
            sih_context.close()
        client.session.close()
        return

    if args.search:
        processed, candidates = _process_search(
            args, client, settings, profile_cache, price_cache,
            sih_reader=sih_reader,
            limiter=limiter,
            browser_context=sih_context,
        )
        logger.info(
            "Done. Processed %d profile(s), %d candidate(s) written to %s.",
            processed, candidates, settings.output_csv,
        )
        if sih_context is not None:
            sih_context.close()
        client.session.close()
        return

    # Determine profile URLs: CLI --urls flag takes priority, otherwise
    # launch a browser session and scrape the trading platform.
    scrapers = {
        "market.csgo.com": MarketCsgoScraper,
        "lis-skins.com": LisSkinsScraper,
        "avan.market": AvanMarketScraper,
    }

    if args.urls:
        profile_urls = args.urls
        context = None
        logger.info("Processing %d URL(s) from --urls argument.", len(profile_urls))
    else:
        # Reuse SIH browser context if already launched, otherwise create a new one
        if sih_context is not None:
            context = sih_context
        else:
            context = launch_persistent_context(settings)
        page = context.new_page()
        scraper_cls = scrapers[args.platform]
        scraper = scraper_cls(page, max_pages=args.max_pages)

        # Create SIH reader from scraper context if not already created
        if sih_reader is None and settings.sih_extension_path and context is not None:
            sih_page = context.new_page()
            sih_reader = SihInventoryReader(sih_page)

        if args.discover:
            base_url = scraper.BASE_URL
            logger.info("Discovery mode: navigating to %s", base_url)
            logger.info("Browse the site manually. Press Ctrl+C when done to collect URLs.")
            scraper._start_response_interception()
            scraper._safe_goto(base_url)
            scraper._wait_for_page_ready()
            found: set[str] = set()
            try:
                while True:
                    page.wait_for_timeout(5_000)
                    found = scraper._collect_all()
                    if found:
                        logger.info(
                            "Discovery: %d Steam URL(s) found so far: %s",
                            len(found),
                            list(found)[:5],
                        )
                    else:
                        logger.info("Discovery: no Steam profile URLs found yet. Keep browsing...")
            except KeyboardInterrupt:
                logger.info("Discovery interrupted by user.")
            # Browser context is dead after Ctrl+C — close it and disable SIH
            # so enrichment falls back to the API-only inventory path.
            try:
                context.close()
            except Exception:
                pass
            context = None
            sih_context = None
            sih_reader = None
            profile_urls = sorted(found)
            logger.info("Discovery finished with %d URL(s).", len(profile_urls))
        else:
            profile_urls = scraper.extract_profile_urls()
            logger.info("Scraper returned %d profile URL(s).", len(profile_urls))

    processed = 0
    candidates = 0

    for profile_url in profile_urls:
        logger.info("Processing: %s", profile_url)

        profile = enrich_profile(
            client, profile_url, args.platform,
            profile_cache=profile_cache, price_cache=price_cache,
            sih_reader=sih_reader, rate_limiter=limiter,
        )
        if profile is None:
            continue

        evaluation = evaluate_profile(profile)
        processed += 1

        logger.info(
            "  -> %s | level=%d vac=%s playtime=%s logoff=%s | candidate=%s%s",
            profile.nickname,
            profile.steam_level,
            profile.vac_banned,
            profile.total_playtime_hours,
            profile.last_logoff,
            evaluation.is_candidate,
            f" (rejected: {', '.join(evaluation.reasons)})" if evaluation.reasons else "",
        )

        if evaluation.is_candidate:
            collected_at = datetime.now(tz=timezone.utc).isoformat()
            write_csv_row(settings.output_csv, profile, evaluation, collected_at)
            candidates += 1

        # Rate-limit between profiles to avoid Steam fraud detection.
        limiter.wait("profile")

    logger.info(
        "Done. Processed %d profile(s), %d candidate(s) written to %s.",
        processed,
        candidates,
        settings.output_csv,
    )

    if context is not None:
        context.close()
    if sih_context is not None and sih_context is not context:
        sih_context.close()
    client.session.close()


if __name__ == "__main__":
    main()
