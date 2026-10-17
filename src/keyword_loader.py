import csv
import json
import os
import re
from typing import List, Optional, Tuple, Dict, Any, Set


def load_keywords_from_file(file_path: str, template: Optional[str] = None) -> List[str]:
    """
    Nạp danh sách từ khóa từ một file (hỗ trợ .csv, .tsv, .txt, .json).

    - CSV / TSV: Tự nhận diện dấu phân cách, lấy cột đầu tiên hoặc cột 'keyword'/'name'/'title'/'dia_danh'.
    - TXT: Mỗi dòng 1 từ khóa, bỏ qua dòng trống hoặc bắt đầu bằng '#'.
    - JSON: Hỗ trợ mảng chuỗi ["kw1", "kw2"] hoặc mảng objects [{"keyword": "kw1"}].
    - Áp dụng template (nếu có, ví dụ: '{keyword} Khánh Hoà').
    - Khử trùng lặp (giữ nguyên thứ tự ban đầu).
    """
    if not os.path.exists(file_path):
        return []

    ext = os.path.splitext(file_path)[1].lower()
    raw_keywords: List[str] = []

    try:
        if ext == ".json":
            with open(file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        raw_keywords.append(item.strip())
                    elif isinstance(item, dict):
                        # Tìm key phù hợp
                        for candidate_key in ("keyword", "name", "title", "dia_danh", "dia_diem", "place", "query"):
                            if candidate_key in item and isinstance(item[candidate_key], str):
                                raw_keywords.append(item[candidate_key].strip())
                                break

        elif ext in (".csv", ".tsv"):
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                sample = f.read(4096)
                f.seek(0)
                delimiter = "\t" if ext == ".tsv" else ","
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                    delimiter = dialect.delimiter
                except Exception:
                    pass

                reader = csv.reader(f, delimiter=delimiter)
                header_checked = False
                target_col_idx = 0

                for row in reader:
                    if not row or not any(field.strip() for field in row):
                        continue

                    # Kiểm tra dòng đầu tiên xem có phải là header không
                    if not header_checked:
                        header_checked = True
                        normalized_headers = [c.strip().lower() for c in row]
                        found_target = False
                        for idx, h in enumerate(normalized_headers):
                            if h in ("keyword", "keywords", "name", "title", "dia_danh", "dia_diem", "place", "places", "từ khóa", "địa danh"):
                                target_col_idx = idx
                                found_target = True
                                break
                        if found_target:
                            # Bỏ qua dòng header
                            continue
                        elif len(row) > 1 and normalized_headers[0] in ("id", "stt", "index", "no"):
                            # Nếu cột 0 là STT/ID thì lấy cột 1
                            target_col_idx = 1
                            continue

                    if len(row) > target_col_idx:
                        val = row[target_col_idx].strip()
                        if val and not val.startswith("#"):
                            raw_keywords.append(val)

        else:
            # Mặc định xử lý như plain text (.txt hoặc định dạng dòng đơn)
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Bỏ bọc ngoặc kép nếu có
                    val = line.strip('"\'')
                    if val:
                        raw_keywords.append(val)

    except Exception:
        return []

    # Áp dụng template và khử trùng lặp
    cleaned_keywords: List[str] = []
    seen: Set[str] = set()

    for kw in raw_keywords:
        if not kw:
            continue
        formatted_kw = template.format(keyword=kw) if template and "{keyword}" in template else kw
        formatted_kw = formatted_kw.strip()
        kw_lower = formatted_kw.lower()
        if formatted_kw and kw_lower not in seen:
            seen.add(kw_lower)
            cleaned_keywords.append(formatted_kw)

    return cleaned_keywords


def resolve_job_keywords(
    job_data: Dict[str, Any],
    base_dir: Optional[str] = None,
) -> Tuple[List[str], List[str], List[str]]:
    """
    Xác định toàn bộ keywords cho một job từ cả nguồn inline và file ngoài.

    Trả về tuple: (keywords_list, watched_files, errors)
    """
    base_dir = base_dir or os.getcwd()
    all_keywords: List[str] = []
    watched_files: List[str] = []
    errors: List[str] = []

    template = job_data.get("keyword_template")

    # 1. Thu thập file nguồn (keywords_file hoặc keywords_files)
    files_to_load = []
    single_file = job_data.get("keywords_file") or job_data.get("places_file")
    if single_file:
        files_to_load.append(single_file)

    multi_files = job_data.get("keywords_files") or job_data.get("places_files")
    if isinstance(multi_files, list):
        for f in multi_files:
            if f and f not in files_to_load:
                files_to_load.append(f)

    # 2. Đọc dữ liệu từ từng file
    for fpath in files_to_load:
        resolved_path = fpath if os.path.isabs(fpath) else os.path.join(base_dir, fpath)
        if not os.path.exists(resolved_path):
            errors.append(f"File từ khóa không tồn tại: '{fpath}' (đường dẫn: {resolved_path})")
            continue

        watched_files.append(os.path.abspath(resolved_path))
        file_kws = load_keywords_from_file(resolved_path, template=template)
        all_keywords.extend(file_kws)

    # 3. Thu thập inline keywords trong YAML
    inline_kws = job_data.get("keywords", [])
    if isinstance(inline_kws, list):
        for kw in inline_kws:
            kw_str = str(kw).strip()
            if kw_str:
                formatted_kw = template.format(keyword=kw_str) if template and "{keyword}" in template else kw_str
                all_keywords.append(formatted_kw.strip())

    # 4. Khử trùng lặp tổng thể
    unique_keywords: List[str] = []
    seen: Set[str] = set()
    for kw in all_keywords:
        if not kw:
            continue
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique_keywords.append(kw)

    return unique_keywords, watched_files, errors
