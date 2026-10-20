import asyncio
import datetime
import json
import logging
import os
import re
import signal
import sys
import traceback
from typing import Dict, Any, List, Optional, Tuple
from croniter import croniter
import yaml
from slugify import slugify
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.models import Place, normalize_place_id, parse_place_id_from_url
from src.scraper import GoogleMapsScraper
from src.scheduler_db import SchedulerDB, DEFAULT_DB_PATH
from src.keyword_loader import resolve_job_keywords
from src.itravels_sync import (
    ITravelsClient,
    normalize_endpoint_type,
    DEFAULT_BASE_URL,
    DEFAULT_SITE,
    DEFAULT_API_KEY,
)

DEFAULT_CONFIG_PATH = "jobs.yaml"
PID_FILE_PATH = os.path.join("data", "cron.pid")
LOGS_DIR = "logs"


def parse_interval_to_seconds(val: str) -> Optional[int]:
    """Chuyển đổi chuỗi như '30m', '6h', '1d', '45s' thành số giây."""
    if not val:
        return None
    val = str(val).strip().lower()
    match = re.match(r"^(\d+)\s*([smhd])$", val)
    if not match:
        return None
    num = int(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return num
    elif unit == "m":
        return num * 60
    elif unit == "h":
        return num * 3600
    elif unit == "d":
        return num * 86400
    return None


def calculate_next_run(
    schedule_cfg: Dict[str, Any], base_dt: Optional[datetime.datetime] = None
) -> Tuple[Optional[datetime.datetime], Optional[str]]:
    """Tính toán thời gian chạy tiếp theo từ schedule config.

    Trả về (next_datetime, error_message).
    """
    if not base_dt:
        base_dt = datetime.datetime.now()

    if not isinstance(schedule_cfg, dict):
        return None, "Schedule phải là một dict (ví dụ: every: 6h hoặc cron: '0 2 * * *')"

    cron_expr = schedule_cfg.get("cron")
    every_expr = schedule_cfg.get("every")

    if cron_expr:
        cron_expr = str(cron_expr).strip()
        if not croniter.is_valid(cron_expr):
            return None, f"Cú pháp cron không hợp lệ: '{cron_expr}'"
        try:
            itr = croniter(cron_expr, base_dt)
            next_run = itr.get_next(datetime.datetime)
            return next_run, None
        except Exception as e:
            return None, f"Lỗi tính toán cron '{cron_expr}': {str(e)}"

    if every_expr:
        sec = parse_interval_to_seconds(every_expr)
        if sec is None or sec <= 0:
            return None, f"Cú pháp every không hợp lệ: '{every_expr}'. Hỗ trợ định dạng: 30m, 2h, 1d, 10s"
        return base_dt + datetime.timedelta(seconds=sec), None

    return None, "Thiếu trường 'every' hoặc 'cron' trong cấu hình schedule"


GLOBAL_SETTINGS: Dict[str, Any] = {}


def get_global_settings() -> Dict[str, Any]:
    return GLOBAL_SETTINGS


class JobConfig:
    def __init__(self, name: str, data: Dict[str, Any], config_dir: Optional[str] = None):
        self.name = name
        self.enabled = bool(data.get("enabled", True))
        self.description = data.get("description", "")
        self.schedule = data.get("schedule", {})
        
        # Hỗ trợ nạp từ khóa linh hoạt từ file (CSV, TXT, JSON...) hoặc inline list
        self.keywords_file = data.get("keywords_file") or data.get("places_file")
        self.keywords_files = data.get("keywords_files") or data.get("places_files")
        self.keyword_template = data.get("keyword_template")
        self.keywords, self.watched_files, self.loader_errors = resolve_job_keywords(
            data, base_dir=config_dir
        )

        self.limit = data.get("limit", None)
        self.max_reviews = data.get("max_reviews", 100)
        self.concurrency = int(data.get("concurrency", 4))
        self.keyword_concurrency = int(data.get("keyword_concurrency", 0))
        self.sort = data.get("sort", "most_relevant")
        self.profile_dir = data.get("profile_dir", "browser_profile")
        self.data_dir = data.get("data_dir", "data")
        self.raw_itravels_type = data.get("itravels_type")
        self.itravels_type = normalize_endpoint_type(self.raw_itravels_type)
        self.auto_sync = bool(data.get("auto_sync", True))
        self.cleanup_old_files = bool(
            data.get("cleanup_old_files", GLOBAL_SETTINGS.get("cleanup_old_files", True))
        )

    def validate(self) -> List[str]:
        errors = []
        if self.loader_errors:
            for err in self.loader_errors:
                errors.append(f"Job '{self.name}': {err}")

        if not self.keywords:
            errors.append(f"Job '{self.name}': Danh sách 'keywords' không được để trống (hoặc file cấu hình từ khóa không có dữ liệu hợp lệ).")
        
        _, sched_err = calculate_next_run(self.schedule)
        if sched_err:
            errors.append(f"Job '{self.name}': {sched_err}")

        if self.limit is not None:
            try:
                lim = int(self.limit)
                if lim <= 0:
                    errors.append(f"Job '{self.name}': 'limit' phải là số nguyên dương hoặc để trống.")
            except ValueError:
                errors.append(f"Job '{self.name}': 'limit' không phải là số hợp lệ.")

        if self.concurrency <= 0:
            errors.append(f"Job '{self.name}': 'concurrency' phải >= 1.")

        if self.raw_itravels_type and not self.itravels_type:
            errors.append(
                f"Job '{self.name}': 'itravels_type' không hợp lệ: '{self.raw_itravels_type}'. "
                f"Chỉ chấp nhận: dia-danh, am-thuc, khach-san, homestay"
            )

        return errors


def load_and_validate_config(config_path: str = DEFAULT_CONFIG_PATH) -> Tuple[Dict[str, JobConfig], List[str]]:
    global GLOBAL_SETTINGS
    if not os.path.exists(config_path):
        return {}, [f"File cấu hình không tồn tại: {config_path}"]

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        return {}, [f"Lỗi đọc cú pháp YAML file '{config_path}': {str(e)}"]

    if not isinstance(raw, dict) or "jobs" not in raw:
        return {}, [f"File cấu hình '{config_path}' phải chứa key 'jobs' ở cấp cao nhất."]

    GLOBAL_SETTINGS = raw.get("settings", {}) if isinstance(raw.get("settings"), dict) else {}

    raw_jobs = raw.get("jobs", {})
    if not isinstance(raw_jobs, dict):
        return {}, ["Key 'jobs' phải là một dictionary chứa các job."]

    config_dir = os.path.dirname(os.path.abspath(config_path))
    jobs = {}
    all_errors = []
    for name, jdata in raw_jobs.items():
        if not isinstance(jdata, dict):
            all_errors.append(f"Job '{name}' cấu hình không đúng định dạng dict.")
            continue
        job_cfg = JobConfig(name, jdata, config_dir=config_dir)
        errs = job_cfg.validate()
        all_errors.extend(errs)
        jobs[name] = job_cfg

    return jobs, all_errors


def setup_job_logger(job_name: str) -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"{job_name}.log")

    logger = logging.getLogger(f"job_{job_name}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def save_job_results_to_json(places: List[Place], keyword: str, job_dir: str) -> str:
    os.makedirs(job_dir, exist_ok=True)
    slug = slugify(keyword, separator="_") if keyword else "places"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.json"
    file_path = os.path.join(job_dir, filename)

    data = [p.to_dict() for p in places]
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path


def save_consolidated_job_results(
    places: List[Place],
    job_name: str,
    job_dir: str,
    timestamp: Optional[str] = None,
) -> str:
    """Gom nhóm toàn bộ địa điểm cào được trong 1 lần chạy job vào 1 file JSON tổng hợp.
    
    Tự động khử trùng lặp dựa trên place_id (hoặc url / title).
    """
    os.makedirs(job_dir, exist_ok=True)
    slug = slugify(job_name, separator="_")
    if not timestamp:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.json"
    file_path = os.path.join(job_dir, filename)

    seen_keys = set()
    unique_places: List[Place] = []
    for p in places:
        if p.place_id:
            p.place_id = normalize_place_id(p.place_id, p.url)
        elif p.url:
            p.place_id = parse_place_id_from_url(p.url)

        key = p.place_id or p.url or (p.title.strip().lower() if p.title else "")
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        unique_places.append(p)

    data = [p.to_dict() for p in unique_places]
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path


def cleanup_old_job_files(
    job_dir: str,
    keep_files: List[str],
    logger: Optional[logging.Logger] = None,
    console: Optional[Console] = None,
) -> int:
    """Xoá các file JSON kết quả cũ của những lần chạy trước trong job_dir, chỉ giữ lại keep_files."""
    if not os.path.exists(job_dir):
        return 0

    keep_abs = {os.path.abspath(f) for f in keep_files if os.path.exists(f)}
    deleted_count = 0

    for fname in os.listdir(job_dir):
        if not fname.endswith(".json"):
            continue
        full_path = os.path.join(job_dir, fname)
        abs_path = os.path.abspath(full_path)

        if abs_path not in keep_abs:
            try:
                os.remove(full_path)
                deleted_count += 1
                msg = f"Đã dọn dẹp file cũ: {full_path}"
                if logger:
                    logger.info(msg)
                if console:
                    console.print(f"    [dim]🗑 {msg}[/dim]")
            except Exception as e:
                err_msg = f"Lỗi xoá file cũ {full_path}: {e}"
                if logger:
                    logger.warning(err_msg)

    return deleted_count


class SchedulerEngine:
    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        db_path: str = DEFAULT_DB_PATH,
        console: Optional[Console] = None,
    ):
        self.config_path = config_path
        self.db = SchedulerDB(db_path)
        self.console = console or Console()
        self.jobs: Dict[str, JobConfig] = {}
        self.last_config_mtime: float = 0
        self.watched_files_mtimes: Dict[str, float] = {}
        self.is_running = False
        self.current_running_job: Optional[str] = None
        self.job_queue: asyncio.Queue = asyncio.Queue()
        self._queued_job_names: set = set()

    def reload_config_if_changed(self) -> bool:
        if not os.path.exists(self.config_path):
            return False

        cfg_mtime = os.path.getmtime(self.config_path)
        changed = False

        if cfg_mtime != self.last_config_mtime:
            changed = True
        else:
            # Kiểm tra thay đổi của các file keyword ngoài (CSV, TXT, JSON...)
            for fpath, old_mtime in self.watched_files_mtimes.items():
                if os.path.exists(fpath):
                    if os.path.getmtime(fpath) != old_mtime:
                        changed = True
                        break
                else:
                    # File ngoài bị xóa
                    changed = True
                    break

        if changed or not self.jobs:
            jobs, errors = load_and_validate_config(self.config_path)
            if errors:
                self.console.print(f"[bold red]⚠️ Lỗi cấu hình {self.config_path}:[/bold red]")
                for e in errors:
                    self.console.print(f"  [red]- {e}[/red]")
                return False

            self.jobs = jobs
            self.itravels_settings = GLOBAL_SETTINGS.get("itravels_api") or GLOBAL_SETTINGS.get("itravels", {})
            self.last_config_mtime = cfg_mtime

            # Cập nhật danh sách theo dõi mtime của các file từ khóa ngoài
            new_watched: Dict[str, float] = {}
            for j in self.jobs.values():
                for fpath in getattr(j, "watched_files", []):
                    if os.path.exists(fpath):
                        new_watched[fpath] = os.path.getmtime(fpath)
            self.watched_files_mtimes = new_watched

            self.console.print(
                f"[bold green]✔ Đã nạp thành công {len(self.jobs)} jobs từ {self.config_path} (Hot-reload)[/bold green]"
            )

            # Cập nhật next_run_at cho các job mới nếu chưa có
            now = datetime.datetime.now()
            for name, j in self.jobs.items():
                if not j.enabled:
                    continue
                state = self.db.get_job_state(name)
                if not state or not state.get("next_run_at"):
                    next_run, _ = calculate_next_run(j.schedule, now)
                    if next_run:
                        self.db.update_next_run(name, next_run.isoformat())
            return True
        return False

    async def run_single_job(
        self,
        job_name: str,
        limit_override: Optional[int] = None,
        headed: bool = False,
        max_keywords_override: Optional[int] = None,
    ) -> bool:
        """Thực thi một job độc lập, bảo đảm bắt lỗi và ghi nhận đầy đủ."""
        if job_name not in self.jobs:
            self.reload_config_if_changed()

        if job_name not in self.jobs:
            self.console.print(f"[bold red]Lỗi: Không tìm thấy job '{job_name}' trong cấu hình.[/bold red]")
            return False

        job_cfg = self.jobs[job_name]
        logger = setup_job_logger(job_name)
        log_file = os.path.join(LOGS_DIR, f"{job_name}.log")

        # Áp dụng giới hạn số từ khóa nếu có (dùng để test nhanh)
        target_keywords = list(job_cfg.keywords)
        if max_keywords_override is not None and max_keywords_override > 0:
            target_keywords = target_keywords[:max_keywords_override]

        effective_limit = limit_override if limit_override is not None else job_cfg.limit
        logger.info(f"=== Bắt đầu thực thi job '{job_name}' ===")
        logger.info(f"Mô tả: {job_cfg.description}")
        logger.info(
            f"Số lượng keyword: {len(target_keywords)} (tổng cấu hình: {len(job_cfg.keywords)}), "
            f"Limit: {effective_limit}, Concurrency: {job_cfg.concurrency}"
        )

        run_id = self.db.start_run(job_name, len(target_keywords), log_file)
        self.current_running_job = job_name

        output_files = []
        all_collected_places: List[Place] = []
        run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        total_places = 0
        success_kw = 0
        failed_kw = 0
        error_msgs = []

        job_output_dir = os.path.join(job_cfg.data_dir, job_name)
        user_profile_dir = os.path.abspath(job_cfg.profile_dir) if job_cfg.profile_dir else None

        scraper = GoogleMapsScraper(
            headless=not headed,
            user_data_dir=user_profile_dir,
            concurrency=job_cfg.concurrency,
        )

        try:
            logger.info("Đang khởi động trình duyệt Playwright...")
            await scraper.start()
            logger.info("Trình duyệt khởi động thành công.")

            # Xác định mức độ song song (concurrency) khi cào danh sách keywords
            # Nếu effective_limit == 1: mỗi keyword chỉ cần 1 tab, dồn toàn bộ concurrency để cào nhiều keywords cùng lúc!
            # Nếu effective_limit > 1 hoặc None: chạy min(concurrency // 2, 2) keywords song song
            kw_concurrency = job_cfg.keyword_concurrency
            if not kw_concurrency or kw_concurrency <= 0:
                if effective_limit == 1:
                    kw_concurrency = max(1, job_cfg.concurrency)
                else:
                    kw_concurrency = max(1, min(len(target_keywords), job_cfg.concurrency // 2 or 1))

            kw_semaphore = asyncio.Semaphore(kw_concurrency)
            kw_lock = asyncio.Lock()

            async def _crawl_single_kw(idx: int, keyword: str):
                nonlocal total_places, success_kw, failed_kw
                async with kw_semaphore:
                    logger.info(f"[{idx}/{len(target_keywords)}] Bắt đầu cào keyword: '{keyword}'")
                    self.console.print(
                        f"[dim]  ↳ [{idx}/{len(target_keywords)}] Đang cào:[/] [cyan]'{keyword}'[/] "
                        f"[dim](limit: {effective_limit or 'all'})[/]"
                    )
                    try:
                        inner_concurrency = 1 if effective_limit == 1 else max(1, job_cfg.concurrency // kw_concurrency)
                        places = await scraper.crawl_keyword(
                            keyword,
                            limit=effective_limit,
                            max_reviews=0 if str(job_cfg.max_reviews).lower() in ("all", "0") else int(job_cfg.max_reviews),
                            sort_by=job_cfg.sort,
                            concurrency=inner_concurrency,
                        )

                        async with kw_lock:
                            if places:
                                all_collected_places.extend(places)
                            total_places += len(places)
                            success_kw += 1
                        logger.info(
                            f"[{idx}/{len(target_keywords)}] Thành công cào '{keyword}': {len(places)} địa điểm"
                        )
                        self.console.print(
                            f"    [green]✔ Xong [{idx}/{len(target_keywords)}] '{keyword}':[/green] {len(places)} địa điểm"
                        )
                    except Exception as kw_err:
                        async with kw_lock:
                            failed_kw += 1
                            err_str = f"Keyword '{keyword}' lỗi: {str(kw_err)}"
                            error_msgs.append(err_str)
                        logger.error(err_str)
                        logger.error(traceback.format_exc())
                        self.console.print(f"    [red]✖ Lỗi cào [{idx}/{len(target_keywords)}] '{keyword}':[/red] {kw_err}")

            if kw_concurrency > 1 and len(target_keywords) > 1:
                logger.info(f"Đang cào {len(target_keywords)} keywords song song (tối đa {kw_concurrency} luồng cùng lúc)...")
                self.console.print(
                    f"[bold cyan]⚡ Đang cào {len(target_keywords)} keywords song song "
                    f"([yellow]{kw_concurrency}[/yellow] luồng đồng thời)...[/bold cyan]"
                )
                await asyncio.gather(*[_crawl_single_kw(idx, kw) for idx, kw in enumerate(target_keywords, 1)])
            else:
                for idx, keyword in enumerate(target_keywords, 1):
                    await _crawl_single_kw(idx, keyword)

        except Exception as job_err:
            failed_kw += len(target_keywords) - (success_kw + failed_kw)
            global_err = f"Lỗi toàn cục trong job '{job_name}': {str(job_err)}"
            error_msgs.append(global_err)
            logger.error(global_err)
            logger.error(traceback.format_exc())
            self.console.print(f"[bold red]✖ Lỗi toàn cục job '{job_name}':[/bold red] {job_err}")
        finally:
            logger.info("Đang đóng trình duyệt Playwright...")
            try:
                await scraper.close()
                logger.info("Đã đóng trình duyệt an toàn.")
            except Exception as close_err:
                logger.warning(f"Lỗi khi đóng trình duyệt: {str(close_err)}")

            self.current_running_job = None
            if job_name in self._queued_job_names:
                self._queued_job_names.remove(job_name)

            # Gom nhóm toàn bộ kết quả vào 1 file JSON tổng hợp của lần chạy này
            if all_collected_places:
                consolidated_path = save_consolidated_job_results(
                    all_collected_places, job_name, job_output_dir, timestamp=run_timestamp
                )
                output_files = [consolidated_path]
                logger.info(f"Đã lưu file tổng hợp {len(all_collected_places)} địa điểm -> {consolidated_path}")
                self.console.print(
                    f"  [bold green]📦 Đã gom nhóm {len(all_collected_places)} địa điểm vào file:[/bold green] [dim]{consolidated_path}[/dim]"
                )

            # Tính toán trạng thái kết thúc
            if failed_kw == 0 and success_kw > 0:
                final_status = "SUCCESS"
            elif success_kw > 0 and failed_kw > 0:
                final_status = "PARTIAL"
            else:
                final_status = "FAILED"

            # Tự động đồng bộ lên iTravels API nếu cấu hình itravels_type và có địa điểm cào thành công
            if job_cfg.itravels_type and job_cfg.auto_sync and output_files and success_kw > 0:
                logger.info(
                    f"Đang tự động đồng bộ {len(output_files)} file kết quả lên iTravels API ({job_cfg.itravels_type})..."
                )
                self.console.print(
                    f"\n[bold cyan]📡 Đang đồng bộ dữ liệu lên iTravels API ([bold yellow]{job_cfg.itravels_type}[/bold yellow])...[/bold cyan]"
                )

                api_client = ITravelsClient(
                    api_key=self.itravels_settings.get("api_key"),
                    base_url=self.itravels_settings.get("base_url", DEFAULT_BASE_URL),
                    site=self.itravels_settings.get("site", DEFAULT_SITE),
                    apply=self.itravels_settings.get("apply", 1),
                    batch_size=self.itravels_settings.get("batch_size", 200),
                    logger=logger,
                )

                sync_errs = []
                for fpath in output_files:
                    sync_ok, sync_msg, _ = api_client.sync_file(fpath, job_cfg.itravels_type)
                    if sync_ok:
                        logger.info(f"✔ iTravels API sync thành công file {fpath}: {sync_msg}")
                        self.console.print(f"    [green]✔ iTravels API:[/] {sync_msg}")
                    else:
                        logger.error(f"✖ iTravels API sync lỗi file {fpath}: {sync_msg}")
                        self.console.print(f"    [red]✖ iTravels API lỗi:[/] {sync_msg}")
                        sync_errs.append(sync_msg)

                if sync_errs:
                    api_err_summary = "iTravels API: " + "; ".join(sync_errs)
                    error_msgs.append(api_err_summary)

            # Tự động dọn dẹp các file JSON kết quả cũ của job này để tránh rác ổ đĩa
            if job_cfg.cleanup_old_files and output_files and success_kw > 0:
                del_count = cleanup_old_job_files(
                    job_output_dir,
                    keep_files=output_files,
                    logger=logger,
                    console=self.console,
                )
                if del_count > 0:
                    logger.info(
                        f"Đã tự động dọn rác: xoá {del_count} file JSON kết quả cũ trong {job_output_dir}"
                    )
                    self.console.print(
                        f"    [dim green]✔ Đã tự động dọn dẹp {del_count} file JSON cũ để tiết kiệm dung lượng.[/dim green]"
                    )

            err_summary = "; ".join(error_msgs) if error_msgs else None
            self.db.finish_run(
                run_id=run_id,
                status=final_status,
                keywords_success=success_kw,
                keywords_failed=failed_kw,
                places_count=total_places,
                error_summary=err_summary,
                output_files=output_files,
            )

            # Tính toán lịch chạy tiếp theo
            next_run, _ = calculate_next_run(job_cfg.schedule)
            if next_run:
                self.db.update_next_run(job_name, next_run.isoformat())

            logger.info(
                f"=== Hoàn thành job '{job_name}': Trạng thái={final_status}, Tổng địa điểm={total_places}, "
                f"Keywords thành công={success_kw}/{len(target_keywords)}, Lần chạy kế tiếp={next_run} ==="
            )

        return final_status == "SUCCESS"

    async def run_jobs(
        self,
        job_names: List[str],
        limit_override: Optional[int] = None,
        headed: bool = False,
        max_keywords_override: Optional[int] = None,
    ) -> Dict[str, bool]:
        """Thực thi lần lượt, tuần tự danh sách các job."""
        results = {}
        total = len(job_names)
        self.console.print(
            f"\n[bold green]🚀 Bắt đầu cào ngay lập tức tuần tự {total} task...[/bold green]\n"
        )
        for idx, name in enumerate(job_names, 1):
            self.console.print(
                f"[bold magenta]═══════════════════════════════════════════════════════════════════[/bold magenta]\n"
                f"[bold cyan]▶ [{idx}/{total}] Đang thực thi task:[/bold cyan] [bold yellow]{name}[/bold yellow]"
            )
            success = await self.run_single_job(
                name,
                limit_override=limit_override,
                headed=headed,
                max_keywords_override=max_keywords_override,
            )
            results[name] = success
            status_text = "[bold green]Thành công ✅[/bold green]" if success else "[bold red]Lỗi hoặc một phần 🔴[/bold red]"
            self.console.print(f"[bold cyan]✔ Kết thúc task {name}:[/bold cyan] {status_text}\n")

        return results

    async def worker_loop(self):
        """Worker tuần tự lấy job từ queue để thực thi."""
        while self.is_running:
            try:
                job_name = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                self.console.print(f"\n[bold cyan]▶ Bắt đầu cào task:[/bold cyan] [yellow]{job_name}[/yellow]")
                await self.run_single_job(job_name)
            except Exception as e:
                self.console.print(f"[bold red]Lỗi bất ngờ trong worker khi chạy job '{job_name}': {e}[/bold red]")
            finally:
                self.job_queue.task_done()

    async def scheduler_loop(self, run_immediately: bool = True):
        """Vòng lặp kiểm tra lịch chạy và reload cấu hình."""
        self.is_running = True
        self.db.mark_stale_running_as_interrupted()
        self.reload_config_if_changed()

        worker_task = asyncio.create_task(self.worker_loop())

        # Khi start cron: chạy ngay lập tức, tuần tự, lần lượt các cron đang bật
        if run_immediately:
            enabled_jobs = [name for name, j in self.jobs.items() if j.enabled]
            if enabled_jobs:
                self.console.print(
                    Panel(
                        f"[bold green]🚀 Kích hoạt chạy ngay lập tức đợt đầu ({len(enabled_jobs)} task tuần tự):[/bold green]\n"
                        f"[yellow]{', '.join(enabled_jobs)}[/yellow]\n\n"
                        f"[dim]Sau khi hoàn thành đợt này, các task sẽ chờ chạy định kỳ theo lịch cron.[/dim]",
                        title="[bold green]Initial Run Activated[/bold green]",
                        border_style="green",
                    )
                )
                for name in enabled_jobs:
                    self._queued_job_names.add(name)
                    await self.job_queue.put(name)

        try:
            while self.is_running:
                # 1. Hot-reload config nếu có sửa file
                self.reload_config_if_changed()

                now = datetime.datetime.now()

                # 2. Kiểm tra các job đến hạn
                for name, j in self.jobs.items():
                    if not j.enabled:
                        continue

                    # Bỏ qua nếu job này đã nằm trong queue hoặc đang chạy
                    if name in self._queued_job_names or self.current_running_job == name:
                        continue

                    state = self.db.get_job_state(name)
                    next_run_str = state.get("next_run_at") if state else None

                    should_run = False
                    if not next_run_str:
                        # Nếu chưa có next_run_at, khởi tạo và đưa vào lịch
                        next_dt, _ = calculate_next_run(j.schedule, now)
                        if next_dt:
                            self.db.update_next_run(name, next_dt.isoformat())
                    else:
                        try:
                            next_dt = datetime.datetime.fromisoformat(next_run_str)
                            if now >= next_dt:
                                should_run = True
                        except Exception:
                            # Nếu format lỗi, tính lại
                            next_dt, _ = calculate_next_run(j.schedule, now)
                            if next_dt:
                                self.db.update_next_run(name, next_dt.isoformat())

                    if should_run:
                        self._queued_job_names.add(name)
                        await self.job_queue.put(name)

                # Ngủ 5 giây trước lần kiểm tra tiếp theo
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            pass
        finally:
            self.is_running = False
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
