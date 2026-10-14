#!/usr/bin/env python3
import os
import sys

# Tự động chuyển sang môi trường ảo .venv nếu chưa kích hoạt
VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python3")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.executable) != os.path.abspath(VENV_PYTHON):
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

import argparse
import glob
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.itravels_sync import (
    ITravelsClient,
    normalize_endpoint_type,
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_SITE,
)
from src.scheduler import load_and_validate_config, DEFAULT_CONFIG_PATH

console = Console()


def find_latest_json_files(job_name: str, data_dir: str = "data") -> list[str]:
    job_dir = os.path.join(data_dir, job_name)
    if not os.path.exists(job_dir):
        return []
    files = glob.glob(os.path.join(job_dir, "*.json"))
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def main():
    parser = argparse.ArgumentParser(
        description="Đồng bộ dữ liệu cào Google Maps lên hệ thống iTravels API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Đường dẫn file JSON cần gửi (ví dụ: data/am_thuc_khanh_hoa/...json)",
    )
    parser.add_argument(
        "--job",
        "-j",
        help="Tên job đã cấu hình trong jobs.yaml (tự động lấy file JSON mới nhất và endpoint type tương ứng)",
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=["dia-danh", "am-thuc", "khach-san", "homestay"],
        help="Loại dữ liệu (dia-danh, am-thuc, khach-san, homestay)",
    )
    parser.add_argument(
        "--site",
        "-s",
        default=DEFAULT_SITE,
        help=f"Mã tỉnh thành (mặc định: {DEFAULT_SITE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chạy thử nghiệm kiểm tra trước (apply=0: chỉ kiểm tra, không ghi vào hệ thống)",
    )
    parser.add_argument(
        "--api-key",
        "-k",
        default=None,
        help="API Key iTravels (mặc định đọc từ jobs.yaml hoặc env ITRAVELS_API_KEY)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Số lượng bản ghi mỗi lô request (mặc định: 200, tối đa: 2000)",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Gửi tất cả các file JSON tìm thấy trong thư mục job (thay vì chỉ file mới nhất)",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="Đường dẫn file jobs.yaml (mặc định: jobs.yaml)",
    )

    args = parser.parse_args()

    # Nạp cấu hình từ jobs.yaml nếu có
    jobs_cfg, _ = load_and_validate_config(args.config)

    endpoint_type = args.type
    target_files = []
    api_key = args.api_key
    site = args.site

    if args.job:
        if args.job not in jobs_cfg:
            console.print(f"[bold red]✖ Không tìm thấy job '{args.job}' trong {args.config}[/bold red]")
            sys.exit(1)

        job_obj = jobs_cfg[args.job]
        if not endpoint_type:
            endpoint_type = getattr(job_obj, "itravels_type", None)

        found_files = find_latest_json_files(args.job, getattr(job_obj, "data_dir", "data"))
        if not found_files:
            console.print(f"[bold yellow]⚠️ Không tìm thấy file JSON kết quả nào trong thư mục của job '{args.job}'.[/bold yellow]")
            sys.exit(1)

        target_files = found_files if args.all_files else [found_files[0]]

    elif args.file:
        if not os.path.exists(args.file):
            console.print(f"[bold red]✖ File không tồn tại: {args.file}[/bold red]")
            sys.exit(1)
        target_files = [args.file]

        # Tự động đoán endpoint_type nếu chưa truyền
        if not endpoint_type:
            lower_file = args.file.lower()
            if "khach_san" in lower_file or "hotel" in lower_file:
                endpoint_type = "khach-san"
            elif "homestay" in lower_file:
                endpoint_type = "homestay"
            elif "dia_danh" in lower_file or "du_lich" in lower_file:
                endpoint_type = "dia-danh"
            elif "am_thuc" in lower_file or "nha_hang" in lower_file or "cafe" in lower_file:
                endpoint_type = "am-thuc"

    else:
        console.print("[bold red]Vui lòng chỉ định file JSON hoặc tên job (--job <job_name>).[/bold red]")
        console.print("[dim]Ví dụ: ./sync_itravels.py --job am_thuc_khanh_hoa[/dim]")
        console.print("[dim]Hoặc:  ./sync_itravels.py data/test.json --type am-thuc --dry-run[/dim]\n")
        sys.exit(1)

    if not endpoint_type:
        console.print("[bold red]✖ Chưa xác định được loại dữ liệu (--type). Vui lòng chọn một trong: dia-danh, am-thuc, khach-san, homestay[/bold red]")
        sys.exit(1)

    norm_type = normalize_endpoint_type(endpoint_type)

    mode_str = "[yellow]KIỂM TRA THỬ (dry-run, apply=0)[/yellow]" if args.dry_run else "[bold green]GHI THỰC TẾ (apply=1)[/bold green]"
    console.print(Panel(
        f"• Loại dữ liệu: [bold cyan]{norm_type}[/bold cyan]\n"
        f"• Tỉnh/Thành (site): [cyan]{site}[/cyan]\n"
        f"• Chế độ: {mode_str}\n"
        f"• Số file cần gửi: [yellow]{len(target_files)}[/yellow]\n"
        f"• Kích thước lô (batch size): [cyan]{args.batch_size}[/cyan]",
        title="[bold cyan]🚀 Đồng Bộ Dữ Liệu Lên iTravels API[/bold cyan]",
        border_style="cyan",
    ))

    client = ITravelsClient(
        api_key=api_key,
        site=site,
        apply=0 if args.dry_run else 1,
        batch_size=args.batch_size,
    )

    total_synced_all = 0
    all_success = True

    for fpath in target_files:
        console.print(f"\n[bold cyan]▶ Đang xử lý file:[/bold cyan] [underline]{fpath}[/underline]")
        success, msg, stats = client.sync_file(fpath, norm_type, dry_run=args.dry_run)

        if success:
            console.print(f"  [bold green]✔ {msg}[/bold green]")
            total_synced_all += stats.get("synced_records", 0)
        else:
            console.print(f"  [bold red]✖ {msg}[/bold red]")
            all_success = False

        # In chi tiết từng lô
        if stats.get("batches"):
            tbl = Table(title="Chi tiết từng lô", show_lines=True)
            tbl.add_column("Lô", justify="center")
            tbl.add_column("Số bản ghi", justify="center")
            tbl.add_column("Mã HTTP", justify="center")
            tbl.add_column("Trạng thái")
            tbl.add_column("Phản hồi server")
            for b in stats["batches"]:
                st_txt = "[green]OK[/green]" if b["success"] else "[red]FAIL[/red]"
                resp_preview = str(b.get("response", {}))
                if len(resp_preview) > 50:
                    resp_preview = resp_preview[:47] + "..."
                tbl.add_row(
                    str(b["batch_index"]),
                    str(b["count"]),
                    str(b["status_code"]),
                    st_txt,
                    resp_preview,
                )
            console.print(tbl)

    if all_success:
        console.print(f"\n[bold green]🎉 Hoàn tất toàn bộ! Tổng cộng {total_synced_all} bản ghi đã được đồng bộ thành công.[/bold green]\n")
    else:
        console.print(f"\n[bold red]⚠️ Quá trình đồng bộ kết thúc với một số lỗi. Hãy kiểm tra chi tiết bảng trên.[/bold red]\n")


if __name__ == "__main__":
    main()
