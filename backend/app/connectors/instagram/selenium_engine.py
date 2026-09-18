"""Headless Selenium scraping engine for Instagram public profiles, posts, and reels.

Provides accurate, zero-session extraction for public accounts without requiring
fragile mobile API session tokens or getting 401/429 blocked by Meta.
"""
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SeleniumInstagramEngine:
    def __init__(self, headless: bool = True, timeout: int = 15):
        self.headless = headless
        self.timeout = timeout

    def _create_driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            if self.headless:
                opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1280,800")
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            driver = webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(self.timeout)
            return driver
        except Exception as exc:
            logger.warning("Failed to initialize Selenium Chrome driver: %s", exc)
            return None

    def is_available(self) -> bool:
        try:
            import selenium
            return True
        except ImportError:
            return False

    def scrape_profile(
        self,
        username: str,
        limit: int = 10,
        since_dt: Optional[datetime] = None,
        until_dt: Optional[datetime] = None
    ) -> Dict[str, Any]:
        user = username.lstrip("@").strip()
        if not user:
            return {"error": "invalid_username"}

        driver = self._create_driver()
        if not driver:
            return {"error": "selenium_driver_unavailable"}

        profile_url = f"https://www.instagram.com/{user}/"
        try:
            driver.get(profile_url)
            time.sleep(2.5)

            page_title = driver.title
            if "Page Not Found" in page_title or "isn't available" in driver.page_source:
                return {"error": "profile_not_found", "notes": [f"@{user} not found on Instagram"]}

            # Extract meta tags
            meta_desc = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:description']\") || {}).content || '';"
            )
            meta_title = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:title']\") || {}).content || '';"
            )
            meta_img = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:image']\") || {}).content || '';"
            )

            followers, following, post_count = None, None, None
            # Format: '4M followers, 168 following, 8,787 posts – see Instagram photos...'
            match = re.search(
                r"([\d\.,KMkm]+)\s+followers,\s*([\d\.,KMkm]+)\s+following,\s*([\d\.,KMkm]+)\s+posts",
                meta_desc,
                re.IGNORECASE
            )
            if match:
                followers = self._parse_count(match.group(1))
                following = self._parse_count(match.group(2))
                post_count = self._parse_count(match.group(3))

            profile_info = {
                "username": user,
                "display_name": meta_title.split("(")[0].strip() if "(" in meta_title else user,
                "followers": followers,
                "following": following,
                "post_count": post_count,
                "biography": meta_desc,
                "verified_account": "Verified" in driver.page_source,
                "url": profile_url,
                "profile_pic_url": meta_img,
                "engine": "selenium_headless"
            }

            # Extract post cards
            posts_data = driver.execute_script("""
                const links = Array.from(document.querySelectorAll("a[href*='/p/'], a[href*='/reel/']"));
                return links.map(a => {
                    const img = a.querySelector('img');
                    return {
                        href: a.href,
                        img: img ? img.src : '',
                        alt: img ? (img.alt || '') : ''
                    };
                });
            """)

            records = []
            seen_urls = set()
            for p in (posts_data or []):
                href = p.get("href", "").strip()
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                shortcode_match = re.search(r"/(?:p|reel)/([^/?#]+)", href)
                shortcode = shortcode_match.group(1) if shortcode_match else href.strip("/").split("/")[-1]

                caption = p.get("alt", "")
                pub_date_str = None
                # Check for date in alt: 'Photo by ... on September 18, 2026'
                date_match = re.search(r"on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", caption)
                if date_match:
                    try:
                        dt = datetime.strptime(date_match.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
                        pub_date_str = dt.isoformat()
                        if since_dt and dt < since_dt:
                            continue
                        if until_dt and dt > until_dt:
                            continue
                    except Exception:
                        pass

                records.append({
                    "id": shortcode,
                    "shortcode": shortcode,
                    "owner_id": user,
                    "username": user,
                    "caption": caption,
                    "url": href,
                    "published_at": pub_date_str,
                    "media": [{"type": "image", "url": p.get("img", "")}],
                    "engagement": {"likes": 0, "comments": 0},
                    "discovery_method": "selenium_profile_dom",
                    "collection_scope": "public_profile_posts"
                })

                if len(records) >= limit:
                    break

            return {
                "profile": profile_info,
                "records": records,
                "warnings": [],
                "notes": ["selenium_engine_success"]
            }
        except Exception as exc:
            logger.exception("Selenium profile scrape failed for @%s: %s", user, exc)
            return {"error": "selenium_scrape_failed", "notes": [str(exc)]}
        finally:
            driver.quit()

    def scrape_single_post(self, url_or_shortcode: str) -> Optional[Dict[str, Any]]:
        target = url_or_shortcode.strip()
        if not target.startswith("http"):
            target = f"https://www.instagram.com/p/{target}/"

        driver = self._create_driver()
        if not driver:
            return None

        try:
            driver.get(target)
            time.sleep(2.0)

            meta_desc = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:description']\") || {}).content || '';"
            )
            meta_title = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:title']\") || {}).content || '';"
            )
            meta_img = driver.execute_script(
                "return (document.querySelector(\"meta[property='og:image']\") || {}).content || '';"
            )

            caption = meta_desc
            author = "Instagram"
            if "on Instagram:" in meta_title:
                author = meta_title.split("on Instagram:")[0].strip()

            shortcode_match = re.search(r"/(?:p|reel)/([^/?#]+)", target)
            shortcode = shortcode_match.group(1) if shortcode_match else target

            return {
                "id": shortcode,
                "shortcode": shortcode,
                "owner_id": author,
                "username": author,
                "caption": caption,
                "title": meta_title,
                "url": target,
                "published_at": None,
                "media": [{"type": "image", "url": meta_img}],
                "engagement": {"likes": 0, "comments": 0},
                "discovery_method": "selenium_single_post",
            }
        except Exception as exc:
            logger.warning("Selenium single post scrape failed for %s: %s", target, exc)
            return None
        finally:
            driver.quit()

    @staticmethod
    def _parse_count(text: str) -> int:
        clean = text.replace(",", "").strip().upper()
        if clean.endswith("K"):
            return int(float(clean[:-1]) * 1000)
        if clean.endswith("M"):
            return int(float(clean[:-1]) * 1000000)
        try:
            return int(float(clean))
        except ValueError:
            return 0
