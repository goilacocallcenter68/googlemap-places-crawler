import datetime
import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Optional, Tuple
import requests

from src.models import normalize_place_id, parse_place_id_from_url

DEFAULT_API_KEY = "PcCnUPgiOnZ0wumxG-ZyX2aBLpdlMGC6OecAyfXPEVM"
DEFAULT_BASE_URL = "https://api.itravels.vn"
DEFAULT_SITE = "khanh-hoa"

ENDPOINT_MAP = {
    "dia-danh": "/api/import/dia-danh",
    "am-thuc": "/api/import/am-thuc",
    "khach-san": "/api/import/khach-san",
    "homestay": "/api/import/homestay",
}


def normalize_endpoint_type(val: str) -> Optional[str]:
    if not val:
        return None
    val = val.strip().lower()
    # Support aliases
    if val in ("dia-danh", "diadanh", "dia_danh", "place", "places"):
        return "dia-danh"
    if val in ("am-thuc", "amthuc", "am_thuc", "food", "cuisine", "restaurant"):
        return "am-thuc"
    if val in ("khach-san", "khachsan", "khach_san", "hotel", "hotels"):
        return "khach-san"
    if val in ("homestay", "home-stay", "home_stay"):
        return "homestay"
    return None


class ITravelsClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        site: str = DEFAULT_SITE,
        apply: int = 1,
        batch_size: int = 200,
        max_retries: int = 4,
        logger: Optional[logging.Logger] = None,
    ):
        self.api_key = api_key or os.environ.get("ITRAVELS_API_KEY") or DEFAULT_API_KEY
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.site = site or DEFAULT_SITE
        self.apply = 1 if apply else 0
        self.batch_size = max(1, min(batch_size, 2000))
        self.max_retries = max_retries
        self.logger = logger or logging.getLogger("itravels_sync")

    def log_info(self, msg: str):
        if self.logger:
            self.logger.info(msg)

    def log_error(self, msg: str):
        if self.logger:
            self.logger.error(msg)

    def log_warning(self, msg: str):
        if self.logger:
            self.logger.warning(msg)

    def send_batch(
        self,
        endpoint_type: str,
        items: List[Dict[str, Any]],
        ngay_cao: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[bool, int, str, Dict[str, Any]]:
        """Gửi 1 lô dữ liệu (items) tới iTravels API.

        Trả về (success, status_code, message, response_json).
        """
        path = ENDPOINT_MAP.get(endpoint_type)
        if not path:
            return False, 400, f"Endpoint type không hợp lệ: '{endpoint_type}'", {}

        url = f"{self.base_url}{path}"
        apply_val = 0 if dry_run else self.apply

        params = {
            "site": self.site,
            "apply": apply_val,
        }

        # Khách sạn và homestay: thêm ngayCao (YYYY-MM-DD)
        if endpoint_type in ("khach-san", "homestay"):
            if not ngay_cao:
                ngay_cao = datetime.datetime.now().strftime("%Y-%m-%d")
            params["ngayCao"] = ngay_cao

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "GoogleMapsCrawler-Sync/1.0",
        }

        # Chuẩn hoá place_id về dạng hex 0x...:0x... trước khi gửi
        normalized_items = []
        for it in items:
            it_dict = dict(it) if isinstance(it, dict) else it
            if isinstance(it_dict, dict):
                norm_id = normalize_place_id(it_dict.get("place_id"), it_dict.get("url"))
                if norm_id:
                    it_dict["place_id"] = norm_id
            normalized_items.append(it_dict)

        retries = 0
        while retries <= self.max_retries:
            try:
                self.log_info(
                    f"Đang gửi request POST tới {url} (params: {params}, items: {len(normalized_items)}, lần thử: {retries + 1})..."
                )
                resp = requests.post(
                    url,
                    params=params,
                    json=normalized_items,
                    headers=headers,
                    timeout=60,
                )

                status_code = resp.status_code
                try:
                    resp_data = resp.json()
                except Exception:
                    resp_data = {"raw_text": resp.text[:500]}

                if status_code in (200, 201):
                    self.log_info(f"✔ Gửi thành công lô {len(items)} bản ghi! Phản hồi: {resp_data}")
                    return True, status_code, "Thành công", resp_data

                elif status_code == 409:
                    # Đang có lượt import khác chạy, chờ rồi gửi lại
                    retries += 1
                    if retries <= self.max_retries:
                        wait_sec = 15 + (retries * 5)
                        self.log_warning(
                            f"⚠️ Gặp lỗi 409 (đang có lượt import khác chạy). Đang chờ {wait_sec}s để thử lại ({retries}/{self.max_retries})..."
                        )
                        time.sleep(wait_sec)
                        continue
                    else:
                        msg = f"Lỗi 409: Server đang có import khác chạy và đã vượt quá {self.max_retries} lần thử lại."
                        self.log_error(msg)
                        return False, status_code, msg, resp_data

                else:
                    msg = f"HTTP {status_code}: {resp_data}"
                    self.log_error(f"✖ Gửi thất bại: {msg}")
                    return False, status_code, msg, resp_data

            except requests.RequestException as req_err:
                retries += 1
                if retries <= self.max_retries:
                    wait_sec = 5 * retries
                    self.log_warning(f"⚠️ Lỗi kết nối mạng: {req_err}. Chờ {wait_sec}s thử lại...")
                    time.sleep(wait_sec)
                    continue
                else:
                    msg = f"Lỗi kết nối sau {self.max_retries} lần thử lại: {str(req_err)}"
                    self.log_error(msg)
                    return False, 0, msg, {}

        return False, 0, "Quá số lần retry cho phép", {}

    def sync_places(
        self,
        endpoint_type: str,
        places: List[Dict[str, Any]],
        ngay_cao: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Chia lô và gửi toàn bộ places tới iTravels API."""
        norm_type = normalize_endpoint_type(endpoint_type)
        if not norm_type:
            return (
                False,
                f"Loại dữ liệu '{endpoint_type}' không hợp lệ. Chỉ chấp nhận: dia-danh, am-thuc, khach-san, homestay",
                {},
            )

        if not places:
            return True, "Không có bản ghi nào để đồng bộ.", {"total": 0, "success": 0}

        # Chuẩn hoá place_id cho toàn bộ bản ghi
        normalized_places = []
        for p in places:
            p_dict = dict(p) if isinstance(p, dict) else p
            if isinstance(p_dict, dict):
                norm_id = normalize_place_id(p_dict.get("place_id"), p_dict.get("url"))
                if norm_id:
                    p_dict["place_id"] = norm_id
            normalized_places.append(p_dict)

        total_records = len(normalized_places)
        batch_size = self.batch_size
        batches = [normalized_places[i : i + batch_size] for i in range(0, total_records, batch_size)]

        self.log_info(
            f"=== Bắt đầu đồng bộ iTravels: {total_records} bản ghi -> chia làm {len(batches)} lô (mỗi lô {batch_size}) ==="
        )

        all_success = True
        synced_count = 0
        failed_batches = 0
        details = []

        for idx, batch in enumerate(batches, 1):
            self.log_info(f"Đang xử lý lô [{idx}/{len(batches)}] ({len(batch)} địa điểm)...")
            success, code, msg, resp_data = self.send_batch(
                endpoint_type=norm_type,
                items=batch,
                ngay_cao=ngay_cao,
                dry_run=dry_run,
            )

            details.append({
                "batch_index": idx,
                "count": len(batch),
                "success": success,
                "status_code": code,
                "message": msg,
                "response": resp_data,
            })

            if success:
                synced_count += len(batch)
            else:
                all_success = False
                failed_batches += 1
                self.log_error(f"Lô [{idx}/{len(batches)}] thất bại: {msg}")

        summary_msg = (
            f"Đã đồng bộ {synced_count}/{total_records} bản ghi ({len(batches) - failed_batches}/{len(batches)} lô thành công)"
        )
        return all_success, summary_msg, {
            "total_records": total_records,
            "synced_records": synced_count,
            "total_batches": len(batches),
            "failed_batches": failed_batches,
            "batches": details,
        }

    def sync_file(
        self,
        file_path: str,
        endpoint_type: str,
        dry_run: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Đọc file JSON và gửi tới iTravels API."""
        if not os.path.exists(file_path):
            return False, f"File không tồn tại: {file_path}", {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return False, f"Lỗi đọc file JSON '{file_path}': {str(e)}", {}

        if not isinstance(data, list):
            return False, f"Dữ liệu trong file '{file_path}' phải là một mảng JSON [ ... ]", {}

        # Trích xuất ngay_cao từ tên file (dạng YYYYMMDD_HHMMSS) hoặc mtime của file
        ngay_cao = None
        match = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}", os.path.basename(file_path))
        if match:
            ngay_cao = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        else:
            file_mtime = os.path.getmtime(file_path)
            ngay_cao = datetime.datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d")

        return self.sync_places(
            endpoint_type=endpoint_type,
            places=data,
            ngay_cao=ngay_cao,
            dry_run=dry_run,
        )
