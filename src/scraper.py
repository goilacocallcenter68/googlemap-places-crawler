import asyncio
import random
import re
import urllib.parse
from typing import List, Optional, Dict, Any, Callable, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from src.models import Place, Review, Coordinates, MenuItem, MenuInfo

SORT_OPTIONS = {
    "most_relevant": "Phù hợp nhất",
    "relevant": "Phù hợp nhất",
    "newest": "Mới nhất",
    "highest_rating": "Xếp hạng cao nhất",
    "highest": "Xếp hạng cao nhất",
    "lowest_rating": "Xếp hạng thấp nhất",
    "lowest": "Xếp hạng thấp nhất",
}

def parse_rating(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    # Matches "4,3", "4.3", "4,3 sao", etc.
    match = re.search(r'(\d+)[,.](\d+)', text)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    match = re.search(r'(\d+)', text)
    if match:
        return float(match.group(1))
    return None

def parse_reviews_count(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    # Matches "(1.166)", "1.166 đánh giá", "1,166 reviews"
    clean = re.sub(r'[^\d]', '', text)
    return int(clean) if clean else None

def parse_coordinates_from_url(url: str) -> Optional[Coordinates]:
    # Matches !3d10.7828453!4d106.6960142 or @10.7828453,106.6960142
    match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if match:
        return Coordinates(latitude=float(match.group(1)), longitude=float(match.group(2)))
    match_d = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if match_d:
        return Coordinates(latitude=float(match_d.group(1)), longitude=float(match_d.group(2)))
    return None

def parse_place_id_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    match = re.search(r'!19s(ChIJ[a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    match_hex = re.search(r'!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)', url)
    if match_hex:
        return match_hex.group(1)
    return None


def clean_image_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None
    # Extract url("...") if wrapped
    match = re.search(r'url\([\'"]?(.*?)[\'"]?\)', raw_url)
    if match:
        raw_url = match.group(1)
    if "googleusercontent.com" in raw_url:
        # Replace thumbnail dimensions with full resolution
        return re.sub(r'=w\d+-h\d+.*$', '=s1600', raw_url)
    return raw_url

class GoogleMapsScraper:
    def __init__(
        self,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        concurrency: int = 4
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.concurrency = max(1, concurrency)
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.browser: Optional[Browser] = None

    async def start(self):
        self.playwright = await async_playwright().start()
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
        ]
        
        if self.user_data_dir:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                args=args,
                locale="vi-VN",
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        else:
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=args
            )
            self.context = await self.browser.new_context(
                locale="vi-VN",
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

        # Pre-seed consent cookie to minimize popups
        await self.context.add_cookies([
            {
                "name": "SOCS",
                "value": "CAESEwgDEgk2ODE4NDk5NzgSGgJ2aRACGg4IgP6YtwYQt_yYtwYyBAgCEAE",
                "domain": ".google.com",
                "path": "/"
            },
            {
                "name": "CONSENT",
                "value": "PENDING+999",
                "domain": ".google.com",
                "path": "/"
            }
        ])

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _handle_consent(self, page: Page):
        try:
            consent_btn = await page.query_selector(
                'button[aria-label*="Đồng ý"], button[aria-label*="Chấp nhận"], button[aria-label*="Accept"], form[action*="consent"] button'
            )
            if consent_btn:
                await consent_btn.click()
                await page.wait_for_timeout(1500)
        except Exception:
            pass

    async def crawl_keyword(
        self,
        keyword: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        concurrency: Optional[int] = None,
        limit: Optional[int] = None,
        max_reviews: Optional[int] = 100,
        sort_by: str = "most_relevant"
    ) -> List[Place]:
        """
        Crawls all places matching the keyword.
        Returns a list of Place objects (or empty list [] if not found).
        """
        page = await self.context.new_page()
        places_data: List[Place] = []

        try:
            search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(keyword)}?hl=vi"
            if progress_callback:
                progress_callback("Đang tìm kiếm trên Google Maps...", 0, 0)
                
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await self._handle_consent(page)

            # Check if this directly navigated to a single place page
            single_h1 = await page.query_selector('h1')
            feed = await page.query_selector('div[role="feed"]')

            if not feed and single_h1:
                # Wait for Google Maps to finish client-side navigation to /maps/place/ URL
                for _ in range(12):
                    if "/maps/place/" in page.url:
                        break
                    await page.wait_for_timeout(500)

                # Single place result directly
                title_text = await single_h1.inner_text()
                if title_text and "kết quả" not in title_text.lower():
                    if progress_callback:
                        progress_callback(f"Tìm thấy 1 địa điểm trực tiếp: {title_text}", 1, 1)

                    direct_url = page.url
                    await page.close()

                    # Open direct place URL in a fresh place page to allow full tab navigation
                    place_page = await self.context.new_page()
                    try:
                        await place_page.goto(direct_url, wait_until="domcontentloaded", timeout=25000)
                        await place_page.wait_for_timeout(2000)
                        await self._handle_consent(place_page)
                        place = await self._extract_place_details(place_page, direct_url, max_reviews=max_reviews, sort_by=sort_by)
                        if place:
                            places_data.append(place)
                    finally:
                        if not place_page.is_closed():
                            await place_page.close()
                    return places_data

            if not feed:
                # Check if 0 results
                if progress_callback:
                    progress_callback("Không tìm thấy kết quả nào.", 0, 0)
                await page.close()
                return []

            # Scroll feed to load places
            if progress_callback:
                limit_msg = f" (tối đa {limit} địa điểm)" if limit else ""
                progress_callback(f"Đang cuộn tải danh sách địa điểm{limit_msg}...", 0, 0)

            place_links: List[str] = []
            seen_links = set()
            consecutive_no_change = 0

            while consecutive_no_change < 4:
                # Find all place links in feed
                links = await feed.query_selector_all('a[href*="/maps/place/"]')
                new_found = False
                for link in links:
                    href = await link.get_attribute("href")
                    if href and href not in seen_links:
                        seen_links.add(href)
                        place_links.append(href)
                        new_found = True
                        if limit and len(place_links) >= limit:
                            break

                if limit and len(place_links) >= limit:
                    if progress_callback:
                        progress_callback(f"Đã đạt giới hạn {limit} địa điểm...", len(place_links), 0)
                    break

                if new_found:
                    consecutive_no_change = 0
                    if progress_callback:
                        progress_callback(f"Đã tìm thấy {len(place_links)} địa điểm...", len(place_links), 0)
                else:
                    consecutive_no_change += 1

                # Check end of list indicator
                end_indicator = await page.query_selector('span.HlvSq, div.PbZDve')
                if end_indicator:
                    txt = await end_indicator.inner_text()
                    if "hết" in txt.lower() or "end" in txt.lower():
                        break

                # Scroll down
                await feed.evaluate('el => el.scrollBy(0, 3000)')
                await page.wait_for_timeout(1500)

            if limit and limit > 0:
                place_links = place_links[:limit]

            total_places = len(place_links)
            if total_places == 0:
                if progress_callback:
                    progress_callback("Không có địa điểm nào phù hợp.", 0, 0)
                await page.close()
                return []

            active_concurrency = max(1, concurrency or self.concurrency)
            if progress_callback:
                progress_callback(f"Tìm thấy {total_places} địa điểm. Đang chuẩn bị cào ({active_concurrency} luồng)...", 0, total_places)

            # Close search page to free up RAM before launching concurrent detail workers
            await page.close()

            semaphore = asyncio.Semaphore(active_concurrency)
            completed_count = 0
            lock = asyncio.Lock()
            results: List[Tuple[int, Optional[Place]]] = []

            async def _crawl_single_place(idx: int, place_url: str):
                nonlocal completed_count
                async with semaphore:
                    # Jitter anti-burst
                    await asyncio.sleep(random.uniform(0.3, 0.8))

                    place: Optional[Place] = None
                    max_retries = 1
                    for attempt in range(max_retries + 1):
                        place_page: Optional[Page] = None
                        try:
                            place_page = await self.context.new_page()

                            # Route blocking: block image, media, font to save RAM and network bandwidth
                            async def _route_filter(route):
                                if route.request.resource_type in ["image", "media", "font"]:
                                    try:
                                        await route.abort()
                                    except Exception:
                                        pass
                                else:
                                    try:
                                        await route.continue_()
                                    except Exception:
                                        pass

                            await place_page.route("**/*", _route_filter)
                            await place_page.goto(place_url, wait_until="domcontentloaded", timeout=25000)
                            await place_page.wait_for_timeout(1800)
                            await self._handle_consent(place_page)
                            place = await self._extract_place_details(place_page, place_url, max_reviews=max_reviews, sort_by=sort_by)
                            if place:
                                break
                        except Exception:
                            if attempt < max_retries:
                                await asyncio.sleep(1.0)
                        finally:
                            if place_page and not place_page.is_closed():
                                try:
                                    await place_page.close()
                                except Exception:
                                    pass

                    async with lock:
                        completed_count += 1
                        results.append((idx, place))
                        if progress_callback:
                            title_info = place.title if (place and place.title) else f"Địa điểm #{idx + 1}"
                            progress_callback(title_info, completed_count, total_places)

                    return place

            # Run all workers concurrently bounded by semaphore
            tasks = [_crawl_single_place(i, url) for i, url in enumerate(place_links)]
            await asyncio.gather(*tasks)

            # Preserve original ranking order from search feed
            results.sort(key=lambda item: item[0])
            places_data = [item[1] for item in results if item[1] is not None]

        finally:
            if not page.is_closed():
                await page.close()

        return places_data

    async def _extract_place_details(
        self,
        page: Page,
        place_url: str,
        max_reviews: Optional[int] = 100,
        sort_by: str = "most_relevant"
    ) -> Optional[Place]:
        """Extracts complete information for a single place."""
        place = Place(url=place_url)

        # Title
        title_el = await page.query_selector('h1')
        if title_el:
            place.title = (await title_el.inner_text()).strip()

        f7nice_el = await page.query_selector('div.F7nice')
        if f7nice_el:
            f7_text = await f7nice_el.inner_text()
            # Check rating
            rating_el = await f7nice_el.query_selector('span[aria-hidden="true"]')
            if rating_el:
                place.rating = parse_rating(await rating_el.inner_text())
            elif f7_text:
                place.rating = parse_rating(f7_text.split()[0] if f7_text else None)

            # Check reviews count: usually inside parentheses like (1.166)
            match_paren = re.search(r'\(([\d.,]+)\)', f7_text)
            if match_paren:
                place.reviews_count = parse_reviews_count(match_paren.group(1))
            else:
                # Try aria-label or last span
                last_span = await f7nice_el.query_selector('span:last-child')
                if last_span:
                    place.reviews_count = parse_reviews_count(await last_span.inner_text())

        # Category
        category_el = await page.query_selector('button[jsaction*="category"]')
        if category_el:
            place.category = (await category_el.inner_text()).strip()

        # Price range
        place.price_range = await self._extract_price_range(page)

        # Address
        addr_el = await page.query_selector(
            'button[data-item-id="address"], button[aria-label*="Địa chỉ:"], button[data-tooltip*="địa chỉ"]'
        )
        if addr_el:
            raw_addr = await addr_el.inner_text()
            place.address = clean_text(raw_addr)

        # Phone
        phone_el = await page.query_selector(
            'button[data-item-id*="phone"], button[aria-label*="Điện thoại:"], button[data-tooltip*="số điện thoại"]'
        )
        if phone_el:
            raw_phone = await phone_el.inner_text()
            place.phone = clean_text(raw_phone)

        # Website
        web_el = await page.query_selector(
            'a[data-item-id*="authority"], a[aria-label*="Trang web:"], a[data-tooltip*="trang web"]'
        )
        if web_el:
            place.website = await web_el.get_attribute("href")

        # Place ID
        place.place_id = parse_place_id_from_url(page.url) or parse_place_id_from_url(place_url)

        # Description / Editorial summary
        desc_el = await page.query_selector('div.WeS02d, div.PYvSYb')
        if desc_el:
            txt = clean_text(await desc_el.inner_text())
            if txt and not any(k in txt for k in ["Ăn tại chỗ", "Giao hàng", "Mang đi", "Dine-in", "Takeaway"]) and len(txt) > 10:
                place.description = txt

        # Plus code
        plus_code_el = await page.query_selector(
            'button[data-item-id*="oloc"], button[aria-label*="Mã cộng"], button[aria-label*="Plus code"]'
        )
        if plus_code_el:
            place.plus_code = clean_text(await plus_code_el.inner_text())

        # Menu
        place.menu = await self._extract_menu(page)

        # Booking / Reservation / Order
        booking_el = await page.query_selector(
            'a[data-item-id*="action:3"], a[data-item-id*="action:order"], a[aria-label*="Đặt bàn"], a[aria-label*="Đặt chỗ"], a[aria-label*="Đặt món"]'
        )
        if booking_el:
            place.booking_link = await booking_el.get_attribute("href")

        # Coordinates
        place.coordinates = parse_coordinates_from_url(page.url) or parse_coordinates_from_url(place_url)

        # Opening Hours
        place.opening_hours = await self._extract_opening_hours(page)

        # Photos
        place.photos = await self._extract_photos(page)

        # About / Tiện nghi, Dịch vụ, Người khuyết tật...
        place.about = await self._extract_about(page)

        # Reviews
        place.reviews = await self._extract_reviews(page, max_reviews=max_reviews, sort_by=sort_by)

        # Fallback: if dishes list is still empty, harvest topic/dish chips from active Reviews tab
        if not place.menu.dishes:
            extra_dishes = await self._extract_dishes_from_active_reviews(page)
            if extra_dishes:
                place.menu.dishes = extra_dishes

        return place

    async def _extract_about(self, page: Page) -> Dict[str, List[str]]:
        """Extracts accessibility, services, amenities, payments, etc. from the About tab."""
        about_data: Dict[str, List[str]] = {}
        try:
            # 1. Switch to "Giới thiệu" (About) tab
            tab_clicked = False
            for _ in range(12):
                tab_locator = page.locator('button[role="tab"]').filter(has_text=re.compile(r'giới thiệu|about', re.I))
                if await tab_locator.count() > 0:
                    is_sel = await tab_locator.first.get_attribute("aria-selected")
                    if is_sel == "true":
                        tab_clicked = True
                        break
                    try:
                        await tab_locator.first.click(timeout=2000)
                    except Exception:
                        await tab_locator.first.evaluate("el => el.click()")
                    await page.wait_for_timeout(800)
                    is_sel = await tab_locator.first.get_attribute("aria-selected")
                    if is_sel == "true":
                        tab_clicked = True
                        break
                else:
                    tabs = await page.query_selector_all('button[role="tab"]')
                    for t in tabs:
                        comb = f"{await t.get_attribute('aria-label') or ''} {await t.inner_text() or ''}".lower()
                        if 'giới thiệu' in comb or 'about' in comb:
                            try:
                                await t.click()
                            except Exception:
                                await t.evaluate("el => el.click()")
                            await page.wait_for_timeout(800)
                            tab_clicked = True
                            break
                    if tab_clicked:
                        break
                await page.wait_for_timeout(400)

            if tab_clicked:
                await page.wait_for_timeout(1200)

                # Scroll about container down once to ensure all sections render
                try:
                    await page.evaluate('''() => {
                        const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb[tabindex="-1"], div.dS8AEf');
                        if (scroller) {
                            scroller.scrollTop += 1500;
                        }
                    }''')
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

                # Extract sections
                raw_sections = await page.evaluate('''() => {
                    const blacklist = [
                        "thông tin chi tiết trên bản đồ",
                        "công cụ bản đồ",
                        "loại bản đồ",
                        "chế độ xem phố",
                        "giao thông",
                        "vệ tinh",
                        "map details",
                        "map tools",
                        "map type"
                    ];
                    const res = {};
                    const allH2 = document.querySelectorAll('h2');
                    allH2.forEach(h2 => {
                        const title = h2.innerText.trim();
                        if (!title) return;
                        if (blacklist.includes(title.toLowerCase())) return;

                        let parent = h2.parentElement;
                        let ul = parent.querySelector('ul') || (parent.parentElement ? parent.parentElement.querySelector('ul') : null);
                        if (ul) {
                            const items = [];
                            ul.querySelectorAll('li').forEach(li => {
                                const aria = (li.getAttribute('aria-label') || '').toLowerCase();
                                const textContent = li.innerText || '';
                                const hasNegativeIcon = textContent.includes('\ue033') || 
                                                      textContent.includes('\ue5cd') ||
                                                      li.querySelector('.m1396b') !== null ||
                                                      li.querySelector('span[aria-label*="Không"], span[aria-label*="không"]') !== null;
                                const isNegative = aria.includes('không') || hasNegativeIcon;

                                if (!isNegative) {
                                    const rawText = li.innerText.trim();
                                    if (rawText) {
                                        items.push(rawText);
                                    }
                                }
                            });
                            if (items.length > 0) {
                                res[title] = items;
                            }
                        }
                    });
                    return res;
                }''')

                for cat, items in raw_sections.items():
                    cleaned_items = []
                    seen_items = set()
                    for it in items:
                        c = clean_text(it)
                        if c and c not in seen_items:
                            seen_items.add(c)
                            cleaned_items.append(c)
                    if cleaned_items:
                        about_data[cat] = cleaned_items

            # Check overview service options if "Lựa chọn dịch vụ" is not yet in about_data
            has_service_key = any("dịch vụ" in k.lower() or "service" in k.lower() for k in about_data.keys())
            if not has_service_key:
                overview_services = await page.evaluate('''() => {
                    const found = [];
                    const chipContainer = document.querySelector('div.PYvSYb, div.E02ZKc');
                    if (chipContainer) {
                        const text = chipContainer.innerText || '';
                        const parts = text.split(/[\\n·•]+/);
                        parts.forEach(p => {
                            const trimmed = p.trim();
                            if (trimmed && !trimmed.startsWith('\\ue033') && !trimmed.toLowerCase().includes('không')) {
                                const clean = trimmed.replace(/[\\ue000-\\uf8ff]/g, '').trim();
                                if (clean && clean.length >= 2 && clean.length <= 40) {
                                    found.push(clean);
                                }
                            }
                        });
                    }
                    return found;
                }''')
                cleaned_services = [clean_text(s) for s in overview_services if clean_text(s)]
                if cleaned_services:
                    about_data["Lựa chọn dịch vụ"] = cleaned_services

        except Exception:
            pass

        return about_data

    async def _extract_price_range(self, page: Page) -> Optional[str]:
        """Extracts price range (e.g. 1.000.000 ₫ trở lên, 200.000–400.000 ₫, ₫₫, $$$) from Overview."""
        def _clean_price_str(raw: Optional[str]) -> Optional[str]:
            if not raw:
                return None
            c = clean_text(raw)
            c = re.sub(r'^[·•\s\-]+|[·•\s\-]+$', '', c).strip()
            c = c.replace('\xa0', ' ')
            return c if c else None

        # Retry up to 5 times (total ~2s) to allow Google Maps async XHR to populate price
        for attempt in range(6):
            try:
                # 1. Inner span with role="img" inside span.mgr77e (contains detailed aria-label or price range)
                img_span = await page.query_selector('span.mgr77e span[role="img"], div.F7nice ~ span.mgr77e span[role="img"]')
                if img_span:
                    aria = await img_span.get_attribute("aria-label")
                    text = await img_span.inner_text()
                    val = aria or text
                    res = _clean_price_str(val)
                    if res:
                        return res

                # 2. Modern Google Maps price container: span.mgr77e
                price_el = await page.query_selector('span.mgr77e')
                if price_el:
                    aria = await price_el.get_attribute("aria-label")
                    text = await price_el.inner_text()
                    val = aria if (aria and ('₫' in aria or '$' in aria or 'giá' in aria.lower())) else text
                    res = _clean_price_str(val)
                    if res:
                        return res

                # 3. Sibling of rating / F7nice container
                f7_price = await page.query_selector('div.F7nice ~ span.mgr77e, div.fontBodyMedium.dmRWX span[role="img"]')
                if f7_price:
                    aria = await f7_price.get_attribute("aria-label")
                    text = await f7_price.inner_text()
                    val = aria or text
                    res = _clean_price_str(val)
                    if res and any(sym in res for sym in ['₫', '$', 'Giá', 'giá', 'trở lên', 'Tr']):
                        return res

                # 4. Fallback aria selectors
                fallback = await page.query_selector(
                    'span[aria-label*="Giá:"], span[aria-label*="Mức giá"], span[aria-label*="Price:"], span[aria-label*="trở lên"]'
                )
                if fallback:
                    aria = await fallback.get_attribute("aria-label")
                    text = await fallback.inner_text()
                    res = _clean_price_str(aria or text)
                    if res:
                        return res
            except Exception:
                pass

            if attempt < 5:
                await page.wait_for_timeout(400)

        return None

    async def _extract_opening_hours(self, page: Page) -> Dict[str, str]:
        hours: Dict[str, str] = {}
        try:
            # Check table rows for opening hours
            rows = await page.query_selector_all('table tr')
            for row in rows:
                txt = await row.inner_text()
                lines = [line.strip() for line in txt.split('\n') if line.strip()]
                if len(lines) >= 2:
                    day = clean_text(lines[0])
                    time_val = clean_text(lines[1])
                    hours[day] = time_val
                elif len(lines) == 1 and ('Thứ' in lines[0] or 'Chủ Nhật' in lines[0]):
                    # Parse combined text like "Thứ Bảy07:00–22:00"
                    match = re.match(r'^(Thứ [^\d:]+|Chủ Nhật)\s*(\d.*)$', lines[0].strip())
                    if match:
                        day = clean_text(match.group(1))
                        time_val = clean_text(match.group(2))
                        hours[day] = time_val
        except Exception:
            pass
        return hours

    async def _extract_photos(self, page: Page) -> List[str]:
        photos = []
        seen = set()
        try:
            # Extract images present in overview
            imgs = await page.query_selector_all('img[src*="googleusercontent.com"], div[style*="googleusercontent.com"]')
            for img in imgs:
                src = await img.get_attribute("src")
                if not src:
                    style = await img.get_attribute("style")
                    src = clean_image_url(style)
                else:
                    src = clean_image_url(src)
                if src and src not in seen and "a-" not in src: # filter user avatar thumbnails
                    seen.add(src)
                    photos.append(src)
        except Exception:
            pass
        return photos

    async def _extract_menu(self, page: Page) -> MenuInfo:
        """Extracts complete menu information including link, dishes, and menu photos."""
        menu_info = MenuInfo()
        try:
            # 1. External menu link
            menu_info.link = await self._extract_menu_link(page)

            # 2. Extract dishes and photos directly from official Thực đơn / Menu tab
            tab_dishes, tab_photos = await self._extract_from_menu_tab(page)
            if tab_dishes:
                menu_info.dishes = tab_dishes
            if tab_photos:
                menu_info.photos = tab_photos

            # 3. Fallback: if no dishes from menu tab, check overview popular dishes & chips
            if not menu_info.dishes:
                menu_info.dishes = await self._extract_overview_popular_dishes(page)

            # 4. Fallback for photos: if no photos from menu tab, check Photos tab
            if not menu_info.photos:
                menu_info.photos = await self._extract_menu_photos(page)

            # Switch back to Overview tab so subsequent extractions (About, Reviews) run properly
            await self._ensure_overview_tab(page)
        except Exception:
            pass

        return menu_info

    async def _extract_menu_link(self, page: Page) -> Optional[str]:
        """Extracts external menu website / ordering URL if present."""
        selectors = [
            'a[data-item-id*="menu"]',
            'a[aria-label*="Thực đơn"]',
            'a[aria-label*="Menu"]',
            'button[data-item-id*="menu"]',
            'a[data-tooltip*="thực đơn"]',
            'a[data-tooltip*="menu"]',
            'a[data-item-id*="action:menu"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        if "google.com/url?" in href:
                            try:
                                parsed = urllib.parse.urlparse(href)
                                qs = urllib.parse.parse_qs(parsed.query)
                                if "q" in qs:
                                    href = qs["q"][0]
                            except Exception:
                                pass
                        return href.strip()
            except Exception:
                pass

        # Fallback: look for any link element with text "Thực đơn" or "Menu" in overview
        try:
            links = await page.evaluate(r'''() => {
                const results = [];
                document.querySelectorAll('a').forEach(a => {
                    const text = (a.innerText || a.getAttribute('aria-label') || '').trim();
                    const href = a.getAttribute('href');
                    if (href && (/^thực đơn$/i.test(text) || /^menu$/i.test(text))) {
                        results.push(href);
                    }
                });
                return results;
            }''')
            if links:
                href = links[0]
                if "google.com/url?" in href:
                    try:
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        if "q" in qs:
                            href = qs["q"][0]
                    except Exception:
                        pass
                return href.strip()
        except Exception:
            pass

        return None

    async def _extract_from_menu_tab(self, page: Page) -> Tuple[List[MenuItem], List[str]]:
        """Checks for official Thực đơn / Menu tab (with retry) and extracts structured dishes and menu photos."""
        dishes: List[MenuItem] = []
        photos: List[str] = []
        try:
            # Wait for tab with text "Thực đơn" or "Menu" (up to 12 retries)
            tab_clicked = False
            for _ in range(12):
                menu_tab = page.locator('button[role="tab"]').filter(has_text=re.compile(r'thực đơn|menu', re.I)).first
                if await menu_tab.count() > 0:
                    try:
                        await menu_tab.click(timeout=2000)
                    except Exception:
                        await menu_tab.evaluate("el => el.click()")
                    tab_clicked = True
                    break
                else:
                    tabs = await page.query_selector_all('button[role="tab"], div[role="tab"], button.hh2c6')
                    for t in tabs:
                        txt = (await t.inner_text() or await t.get_attribute("aria-label") or "").strip().lower()
                        if "thực đơn" in txt or "menu" in txt:
                            try:
                                await t.click()
                            except Exception:
                                await t.evaluate("el => el.click()")
                            tab_clicked = True
                            break
                    if tab_clicked:
                        break
                await page.wait_for_timeout(400)

            if not tab_clicked:
                return [], []

            await page.wait_for_timeout(1500)

            # Scroll menu container down to load all items and photos
            try:
                for _ in range(6):
                    await page.evaluate('''() => {
                        const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb[tabindex="-1"], div.dS8AEf');
                        if (scroller) scroller.scrollTop += 1500;
                    }''')
                    await page.wait_for_timeout(500)
            except Exception:
                pass

            data = await page.evaluate(r'''() => {
                const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb[tabindex="-1"], div.dS8AEf');
                if (!scroller) return { rawDishes: [], rawPhotos: [] };

                const rawDishes = [];
                const rawPhotos = [];
                const seenP = new Set();
                const seenN = new Set();

                // 1. Process all dish cards: div.ofKBgf, div.XiKgde, div[jscontroller], cards
                const cards = scroller.querySelectorAll('div.ofKBgf, div.XiKgde, div[jscontroller="AGAKid"], div.wcwwRb, div.U7v8Je');
                for (const c of cards) {
                    const nameEl = c.querySelector('span.zaTlhd, div.KoY8Lc, div.fontBodyMedium, div.fontTitleSmall, div[role="heading"], h3, h4');
                    let name = nameEl ? nameEl.innerText.trim() : '';
                    if (!name) {
                        const firstLine = (c.innerText || '').split('\n')[0].trim();
                        if (firstLine && firstLine.length < 50 && !firstLine.includes('₫') && !firstLine.includes('$') && firstLine !== 'Điểm nổi bật' && firstLine !== 'Menu') {
                            name = firstLine;
                        }
                    }

                    let price = null;
                    const priceMatch = (c.innerText || '').match(/([\d.,]+\s*(?:₫|đ|VND|VNĐ|k|\$|USD))/i);
                    if (priceMatch) price = priceMatch[1].trim();

                    const img = c.querySelector('img[src*="googleusercontent.com"], div[style*="googleusercontent.com"]');
                    let photo = img ? (img.getAttribute('src') || img.style.backgroundImage || '') : '';

                    if (photo) {
                        rawPhotos.push(photo);
                        seenP.add(photo);
                    }
                    if (name && !seenN.has(name.toLowerCase())) {
                        seenN.add(name.toLowerCase());
                        rawDishes.push({ name, price, photo: photo || null });
                    }
                }

                // 2. Also check traditional menu items or list items if structured menu
                const traditionalItems = scroller.querySelectorAll('div.m6QErb > div[role="button"], div.Gpq6kf');
                for (const item of traditionalItems) {
                    const title = item.querySelector('div.fontTitleSmall, div[role="heading"]');
                    let name = title ? title.innerText.trim() : '';
                    if (name && !seenN.has(name.toLowerCase())) {
                        seenN.add(name.toLowerCase());
                        let price = null;
                        const priceMatch = (item.innerText || '').match(/([\d.,]+\s*(?:₫|đ|VND|VNĐ|k|\$|USD))/i);
                        if (priceMatch) price = priceMatch[1].trim();
                        rawDishes.push({ name, price, photo: null });
                    }
                }

                // 3. Collect all images in menu scroller
                const allImgEls = scroller.querySelectorAll('img[src*="googleusercontent.com"], div[style*="googleusercontent.com"]');
                for (const el of allImgEls) {
                    const src = el.getAttribute('src') || el.style.backgroundImage || '';
                    if (src && !seenP.has(src)) {
                        seenP.add(src);
                        rawPhotos.push(src);
                    }
                }

                return { rawDishes, rawPhotos };
            }''')

            seen_photos = set()
            for rd in data['rawDishes']:
                dishes.append(MenuItem(
                    name=clean_text(rd['name']),
                    price=clean_text(rd.get('price')) if rd.get('price') else None,
                    photo=clean_image_url(rd.get('photo')) if rd.get('photo') else None
                ))

            for rp in data['rawPhotos']:
                cleaned = clean_image_url(rp)
                if cleaned and cleaned not in seen_photos and 'a-' not in cleaned:
                    seen_photos.add(cleaned)
                    photos.append(cleaned)

        except Exception:
            pass

        return dishes, photos

    async def _extract_overview_popular_dishes(self, page: Page) -> List[MenuItem]:
        """Extracts popular dishes / dishes mentioned from Overview."""
        dishes: List[MenuItem] = []
        seen_names = set()

        try:
            # 1. Popular dishes section in Overview
            popular_items = await page.evaluate(r'''() => {
                const results = [];
                const headings = Array.from(document.querySelectorAll('h2, h3, div[role="heading"]'))
                    .filter(h => /món ăn phổ biến|món phổ biến|món nổi bật|popular dishes/i.test(h.innerText));
                
                for (const h of headings) {
                    const container = h.closest('div.m6QErb, div.section-layout') || h.parentElement;
                    if (!container) continue;
                    const cards = container.querySelectorAll('div[role="button"], div.fontHeadlineSmall, div.Gpq6kf');
                    for (const c of cards) {
                        const txt = c.innerText.trim();
                        if (txt && txt.length < 60) {
                            const lines = txt.split('\n').map(l => l.trim()).filter(Boolean);
                            const name = lines[0];
                            const desc = lines.length > 1 ? lines.slice(1).join(' - ') : null;
                            const img = c.querySelector('img[src*="googleusercontent.com"], div[style*="googleusercontent.com"]');
                            const photo = img ? (img.getAttribute('src') || img.getAttribute('style')) : null;
                            results.push({ name, description: desc, photo });
                        }
                    }
                }
                return results;
            }''')

            for p in popular_items:
                name = clean_text(p.get("name", ""))
                if name and name.lower() not in seen_names and len(name) >= 3:
                    seen_names.add(name.lower())
                    photo = clean_image_url(p.get("photo")) if p.get("photo") else None
                    dishes.append(MenuItem(
                        name=name,
                        description=clean_text(p.get("description")) if p.get("description") else None,
                        photo=photo
                    ))

            # 2. Topic chips in Overview (if available before clicking Reviews)
            topic_chips = await page.evaluate(r'''() => {
                const chips = [];
                const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb.DsmM0c, div.dS8AEf');
                if (!scroller) return chips;
                const els = scroller.querySelectorAll('button.e2CuFe, div.fp6G2d');
                for (const el of els) {
                    const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    if (text) chips.push(text);
                }
                return chips;
            }''')

            generic_stop_words = {
                "tất cả", "all", "giá", "giá cả", "price", "phục vụ", "dịch vụ", "service",
                "không gian", "view", "nhân viên", "staff", "vị trí", "địa điểm", "location",
                "quán", "nhà hàng", "restaurant", "đồ ăn", "thức ăn", "ẩm thực", "food",
                "chất lượng", "vệ sinh", "chỗ ngồi", "bàn", "chờ", "thanh toán", "tiền",
                "mới nhất", "xếp hạng cao nhất", "phù hợp nhất", "trải nghiệm",
                "mặc định", "vệ tinh", "địa hình", "giao thông", "chế độ xem phố", "bản đồ",
                "chia sẻ", "lưu", "đường đi", "gần đó", "gửi tới điện thoại", "thêm ảnh",
                "thêm ảnh và video", "viết bài đánh giá", "đề xuất chỉnh sửa", "ảnh", "bài đánh giá",
                "tổng quan", "giới thiệu", "thực đơn", "menu"
            }

            for raw_chip in topic_chips:
                raw_clean = clean_text(raw_chip)
                match = re.search(r'^(.*?)\s*\((\d+)\)$', raw_clean)
                if match:
                    dish_name = clean_text(match.group(1))
                    count_str = match.group(2)
                    if (
                        dish_name
                        and dish_name.lower() not in generic_stop_words
                        and dish_name.lower() not in seen_names
                        and len(dish_name) >= 3
                    ):
                        seen_names.add(dish_name.lower())
                        dishes.append(MenuItem(
                            name=dish_name,
                            description=f"{count_str} lượt nhắc trong đánh giá"
                        ))
        except Exception:
            pass

        return dishes

    async def _extract_menu_photos(self, page: Page) -> List[str]:
        """Extracts menu photos from Photos tab under Thực đơn category (no limit)."""
        menu_photos: List[str] = []
        seen_photos = set()

        try:
            # 1. Open Photos tab
            photo_tab = page.locator('button[role="tab"]').filter(has_text=re.compile(r'ảnh|photos', re.I)).first
            photo_opened = False
            if await photo_tab.count() > 0:
                try:
                    await photo_tab.click(timeout=2000)
                    await page.wait_for_timeout(1200)
                    photo_opened = True
                except Exception:
                    pass

            if not photo_opened:
                photo_btn = page.locator('button:has-text("Xem ảnh"), button[aria-label*="Ảnh của"], button[jsaction*="heroHeaderImage"]').first
                if await photo_btn.count() > 0:
                    try:
                        await photo_btn.click(timeout=2000)
                        await page.wait_for_timeout(1200)
                        photo_opened = True
                    except Exception:
                        pass

            if not photo_opened:
                return []

            # 2. Find and click "Thực đơn" / "Menu" category button
            menu_cat_btn = page.locator(
                'button[role="tab"], button[role="radio"], button.Gpq6kf, div.Gpq6kf, button[aria-label*="Thực đơn"], button[aria-label*="Menu"]'
            ).filter(has_text=re.compile(r'thực đơn|menu', re.I)).first

            if await menu_cat_btn.count() == 0:
                return []

            try:
                await menu_cat_btn.click(timeout=2000)
                await page.wait_for_timeout(1500)
            except Exception:
                await menu_cat_btn.evaluate("el => el.click()")
                await page.wait_for_timeout(1500)

            # 3. Scroll to load all menu photos until exhausted
            consecutive_no_new = 0
            for _ in range(25):
                imgs = await page.evaluate(r'''() => {
                    const urls = [];
                    const all = document.querySelectorAll('img[src*="googleusercontent.com"], div[style*="googleusercontent.com"], a[data-photo-index] div');
                    for (const el of all) {
                        const src = el.getAttribute('src') || el.getAttribute('style') || '';
                        if (src.includes('googleusercontent.com')) {
                            urls.push(src);
                        }
                    }
                    return urls;
                }''')

                new_found = False
                for raw_url in imgs:
                    cleaned = clean_image_url(raw_url)
                    if cleaned and cleaned not in seen_photos and "a-" not in cleaned:
                        seen_photos.add(cleaned)
                        menu_photos.append(cleaned)
                        new_found = True

                if new_found:
                    consecutive_no_new = 0
                else:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        break

                # Scroll photo container
                try:
                    await page.evaluate('''() => {
                        const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb[tabindex="-1"], div.dS8AEf');
                        if (scroller) scroller.scrollTop += 2000;
                    }''')
                    await page.wait_for_timeout(600)
                except Exception:
                    break

        except Exception:
            pass

        return menu_photos

    async def _ensure_overview_tab(self, page: Page):
        """Switches back to Overview tab if another tab was active."""
        try:
            overview_tab = page.locator('button[role="tab"]').filter(has_text=re.compile(r'tổng quan|overview', re.I)).first
            if await overview_tab.count() > 0:
                is_sel = await overview_tab.get_attribute("aria-selected")
                if is_sel != "true":
                    await overview_tab.click(timeout=1500)
                    await page.wait_for_timeout(600)
            else:
                back_btn = page.locator('button[aria-label*="Quay lại"], button[aria-label*="Back"], button.hV1i2e').first
                if await back_btn.count() > 0:
                    await back_btn.click(timeout=1500)
                    await page.wait_for_timeout(600)
        except Exception:
            pass

    async def _extract_dishes_from_active_reviews(self, page: Page) -> List[MenuItem]:
        """Harvests dish names from topic filter chips when Reviews tab is active."""
        dishes: List[MenuItem] = []
        seen = set()
        try:
            chips = await page.evaluate(r'''() => {
                const results = [];
                const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb.DsmM0c, div.dS8AEf');
                if (!scroller) return results;
                const els = scroller.querySelectorAll('button.e2CuFe, div.fp6G2d');
                for (const el of els) {
                    const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    if (t) results.push(t);
                }
                return results;
            }''')

            generic_stop_words = {
                "tất cả", "all", "giá", "giá cả", "price", "phục vụ", "dịch vụ", "service",
                "không gian", "view", "nhân viên", "staff", "vị trí", "địa điểm", "location",
                "quán", "nhà hàng", "restaurant", "đồ ăn", "thức ăn", "ẩm thực", "food",
                "chất lượng", "vệ sinh", "chỗ ngồi", "bàn", "chờ", "thanh toán", "tiền",
                "mới nhất", "xếp hạng cao nhất", "phù hợp nhất", "trải nghiệm",
                "mặc định", "vệ tinh", "địa hình", "giao thông", "chế độ xem phố", "bản đồ",
                "chia sẻ", "lưu", "đường đi", "gần đó", "gửi tới điện thoại", "thêm ảnh",
                "thêm ảnh và video", "viết bài đánh giá", "đề xuất chỉnh sửa", "ảnh", "bài đánh giá",
                "tổng quan", "giới thiệu", "thực đơn", "menu"
            }

            for raw in chips:
                raw_clean = clean_text(raw)
                match = re.search(r'^(.*?)\s*\((\d+)\)$', raw_clean)
                if match:
                    name = clean_text(match.group(1))
                    count = match.group(2)
                    if (
                        name
                        and name.lower() not in generic_stop_words
                        and name.lower() not in seen
                        and len(name) >= 3
                    ):
                        seen.add(name.lower())
                        dishes.append(MenuItem(name=name, description=f"{count} lượt nhắc trong đánh giá"))
        except Exception:
            pass
        return dishes

    async def _extract_reviews(
        self,
        page: Page,
        max_reviews: Optional[int] = 100,
        sort_by: str = "most_relevant"
    ) -> List[Review]:
        reviews: List[Review] = []
        try:
            target_count = max_reviews if (max_reviews is not None and max_reviews > 0) else float('inf')
            target_sort_text = SORT_OPTIONS.get(sort_by, "Phù hợp nhất")

            # 1. Switch to "Bài đánh giá" tab (Google Maps renders this tab asynchronously)
            tab_clicked = False
            for _ in range(16):
                tab_locator = page.locator('button[role="tab"]').filter(has_text=re.compile(r'đánh giá|reviews', re.I))
                if await tab_locator.count() > 0:
                    is_sel = await tab_locator.first.get_attribute("aria-selected")
                    if is_sel == "true":
                        tab_clicked = True
                        break
                    try:
                        await tab_locator.first.click(timeout=3000)
                    except Exception:
                        await tab_locator.first.evaluate("el => el.click()")
                    await page.wait_for_timeout(800)
                    is_sel = await tab_locator.first.get_attribute("aria-selected")
                    if is_sel == "true":
                        tab_clicked = True
                        break
                else:
                    tabs = await page.query_selector_all('button[role="tab"], button.hh2c6')
                    for t in tabs:
                        comb = f"{await t.get_attribute('aria-label') or ''} {await t.inner_text() or ''}".lower()
                        if ('đánh giá' in comb or 'review' in comb) and 'viết' not in comb:
                            try:
                                await t.click()
                            except Exception:
                                await t.evaluate("el => el.click()")
                            await page.wait_for_timeout(800)
                            is_sel = await t.get_attribute("aria-selected")
                            if is_sel == "true":
                                tab_clicked = True
                                break
                    if tab_clicked:
                        break
                await page.wait_for_timeout(500)

            # Fallback: check for more reviews button or reviews header button
            if not tab_clicked:
                more_rev_btn = page.locator(
                    'button[jsaction*="moreReviews"], button[aria-label*="Bài đánh giá khác"], button:has-text("Bài đánh giá khác"), button:has-text("Xem các bài đánh giá khác")'
                ).first
                if await more_rev_btn.count() > 0:
                    try:
                        await more_rev_btn.click(timeout=3000)
                        await page.wait_for_timeout(1500)
                        tab_clicked = True
                    except Exception:
                        pass

            # Check if active tab is reviews
            if not tab_clicked:
                active_tab = page.locator('button[role="tab"][aria-selected="true"]').first
                if await active_tab.count() > 0:
                    txt = (await active_tab.inner_text()).lower()
                    if 'đánh giá' in txt or 'review' in txt:
                        tab_clicked = True

            # If we could not activate the Reviews tab, this place has no separate reviews section
            if not tab_clicked:
                return []

            # Dismiss login/cookie modal if present
            dialog_close = page.locator(
                'div[role="dialog"] button[aria-label*="Đóng"], div[role="dialog"] button:has-text("Loại bỏ"), div[role="dialog"] button:has-text("Không, cảm ơn")'
            ).first
            if await dialog_close.count() > 0:
                try:
                    await dialog_close.click(timeout=1000)
                    await page.wait_for_timeout(300)
                except Exception:
                    pass

            # 2. Select sort option if sort button exists
            sort_btn = page.locator('button[aria-label*="Sắp xếp bài đánh giá"], button[aria-label*="Sắp xếp"], button:has-text("Sắp xếp")').first
            if await sort_btn.count() > 0:
                try:
                    await sort_btn.click(timeout=2000)
                    await page.wait_for_timeout(500)
                    target_opt = page.locator('div[role="menuitemradio"], div[role="menuitem"]').filter(has_text=target_sort_text).first
                    if await target_opt.count() > 0:
                        checked = await target_opt.get_attribute("aria-checked")
                        if checked != "true":
                            await target_opt.click(timeout=2000)
                            await page.wait_for_timeout(1500)
                        else:
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(300)
                    else:
                        await page.keyboard.press("Escape")
                except Exception:
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass

            # 3. Wait for review cards to appear
            for _ in range(10):
                cards_check = await page.query_selector_all('div.jftiEf')
                if cards_check:
                    break
                await page.wait_for_timeout(400)

            # 4. Continuous Infinite Scroll loop to fetch reviews up to target_count
            last_count = 0
            consecutive_no_change = 0
            max_scroll_iterations = 200 if target_count == float('inf') else max(10, int(target_count // 10) + 8)

            # Focus the reviews container for keyboard scrolling and get its bounding box
            container = page.locator('div.m6QErb.DxyBCb, div.m6QErb.DsmM0c, div.dS8AEf').first
            box = None
            if await container.count() > 0:
                try:
                    await container.focus()
                except Exception:
                    pass
                try:
                    box = await container.bounding_box()
                except Exception:
                    pass

            for _ in range(max_scroll_iterations):
                cards = await page.query_selector_all('div.jftiEf')
                current_count = len(cards)

                if current_count >= target_count:
                    break

                if current_count > last_count:
                    consecutive_no_change = 0
                    last_count = current_count
                else:
                    consecutive_no_change += 1
                    if consecutive_no_change >= 5:
                        break

                # Scroll down using keyboard PageDown + mouse wheel + scrollTop + scrollIntoView
                try:
                    await page.keyboard.press("PageDown")
                except Exception:
                    pass

                if box:
                    try:
                        await page.mouse.move(box['x'] + min(200, box['width'] / 2), box['y'] + min(300, box['height'] / 2))
                        await page.mouse.wheel(0, 3000)
                    except Exception:
                        pass

                await page.evaluate('''() => {
                    const cards = document.querySelectorAll('div.jftiEf');
                    if (cards.length > 0) {
                        cards[cards.length - 1].scrollIntoView({ behavior: 'auto', block: 'end' });
                    }
                    const scroller = document.querySelector('div.m6QErb.DxyBCb, div.m6QErb.DsmM0c[tabindex="-1"], div.m6QErb.DsmM0c, div.dS8AEf');
                    if (scroller) {
                        scroller.scrollTop = scroller.scrollHeight;
                        scroller.dispatchEvent(new Event('scroll', { bubbles: true }));
                    }
                }''')
                await page.wait_for_timeout(1000)

            # 5. Expand truncated review text ("Xem thêm" / "More")
            await page.evaluate('''() => {
                const btns = document.querySelectorAll('button.w8nwRe, button[aria-label*="Xem thêm"], button[aria-label*="More"]');
                btns.forEach(b => {
                    try { b.click(); } catch (e) {}
                });
            }''')
            await page.wait_for_timeout(400)

            # 6. Extract review cards with deduplication
            cards = await page.query_selector_all('div.jftiEf')
            if target_count < float('inf'):
                cards = cards[:int(target_count)]

            seen_keys = set()
            for card in cards:
                try:
                    r = Review()
                    # Author
                    auth_el = await card.query_selector('.d4r55')
                    if auth_el:
                        r.author = (await auth_el.inner_text()).strip()

                    # Author link
                    auth_btn = await card.query_selector('button.al6Kxe, a[href*="contrib"]')
                    if auth_btn:
                        r.author_url = await auth_btn.get_attribute('data-href') or await auth_btn.get_attribute('href')

                    # Rating
                    star_el = await card.query_selector('span.kvMYJc')
                    if star_el:
                        star_aria = await star_el.get_attribute('aria-label')
                        r.rating = parse_rating(star_aria)

                    # Date
                    date_el = await card.query_selector('span.rsqaWe')
                    if date_el:
                        r.publish_date = (await date_el.inner_text()).strip()

                    # Content
                    content_el = await card.query_selector('span.wiI7pd')
                    if content_el:
                        r.content = (await content_el.inner_text()).strip()

                    # Photos in review
                    r_photos = []
                    photo_elements = await card.query_selector_all(
                        'button[style*="background-image"], div[style*="background-image"], button[data-photo-index], div.KtCyie button'
                    )
                    for pe in photo_elements:
                        style = await pe.get_attribute('style')
                        img_url = clean_image_url(style)
                        if img_url and 'googleusercontent.com/a-/' not in img_url and 'avatar' not in img_url:
                            if img_url not in r_photos:
                                r_photos.append(img_url)
                    r.review_photos = r_photos

                    # Owner response
                    owner_el = await card.query_selector('div.CDe7pd')
                    if owner_el:
                        r.owner_response = (await owner_el.inner_text()).strip()

                    if r.author or r.content:
                        dedup_key = (r.author, r.publish_date, r.content[:40] if r.content else '')
                        if dedup_key not in seen_keys:
                            seen_keys.add(dedup_key)
                            reviews.append(r)
                except Exception:
                    continue

        except Exception:
            pass

        return reviews

def clean_text(val: Optional[str]) -> str:
    if not val:
        return ""
    # Strip icons and unnecessary whitespace
    cleaned = re.sub(r'[\ue000-\uf8ff]', '', val)
    cleaned = re.sub(r'[\n]+', ' ', cleaned)
    return cleaned.strip()
