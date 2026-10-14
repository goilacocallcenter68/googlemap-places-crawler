#!/usr/bin/env python3
import os
import sys

# Tự động chuyển sang môi trường ảo .venv nếu chưa kích hoạt
VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python3")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.executable) != os.path.abspath(VENV_PYTHON):
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

import argparse
import asyncio
import datetime
import signal
import subprocess
import time
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.scheduler import (
    SchedulerEngine,
    load_and_validate_config,
    calculate_next_run,
    get_global_settings,
    DEFAULT_CONFIG_PATH,
    PID_FILE_PATH,
    LOGS_DIR,
)
from src.scheduler_db import SchedulerDB, DEFAULT_DB_PATH

console = Console()


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def get_daemon_pid() -> Optional[int]:
    if not os.path.exists(PID_FILE_PATH):
        return None
    try:
        with open(PID_FILE_PATH, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        if is_process_alive(pid):
            return pid
        else:
            # Stale PID file
            try:
                os.remove(PID_FILE_PATH)
            except OSError:
                pass
            return None
    except Exception:
        return None


def format_relative_time(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        now = datetime.datetime.now()
        diff = (dt - now).total_seconds()
        
        if abs(diff) < 60:
            return "vài giây trước" if diff < 0 else "trong vài giây"
        
        minutes = int(abs(diff) // 60)
        hours = int(minutes // 60)
        days = int(hours // 24)

        if days > 0:
            time_part = f"{days}d {hours % 24}h"
        elif hours > 0:
            time_part = f"{hours}h {minutes % 60}m"
        else:
            time_part = f"{minutes}m"

        if diff < 0:
            return f"{dt.strftime('%H:%M %d/%m')} ({time_part} trước)"
        else:
            return f"{dt.strftime('%H:%M %d/%m')} (sau {time_part})"
    except Exception:
        return str(dt_str)


# -----------------------------------------------------------------------------
# COMMAND: status
# -----------------------------------------------------------------------------
def cmd_status(args):
    db = SchedulerDB(DEFAULT_DB_PATH)
    jobs_cfg, cfg_errors = load_and_validate_config(args.config)
    pid = get_daemon_pid()

    # Banner daemon status
    if pid:
        console.print(Panel(
            f"[bold green]✔ Scheduler Daemon ĐANG CHẠY[/bold green] (PID: [cyan]{pid}[/cyan])\n"
            f"File config: [dim]{args.config}[/dim] | CSDL: [dim]{DEFAULT_DB_PATH}[/dim]",
            title="[bold cyan]Google Maps Cronjob Status[/bold cyan]",
            border_style="green",
        ))
    else:
        console.print(Panel(
            "[bold yellow]⏸ Scheduler Daemon HIỆN ĐANG DỪNG[/bold yellow]\n"
            "Chạy `python cron.py start` (foreground) hoặc `python cron.py start -d` (daemon ngầm) để kích hoạt.",
            title="[bold yellow]Google Maps Cronjob Status[/bold yellow]",
            border_style="yellow",
        ))

    if cfg_errors:
        console.print("[bold red]⚠️ Cảnh báo lỗi cú pháp trong file config:[/bold red]")
        for err in cfg_errors:
            console.print(f"  [red]- {err}[/red]")
        console.print("")

    table = Table(
        title="Danh sách Tác vụ Định kỳ (Jobs)",
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("Tên Job", style="cyan", no_wrap=True)
    table.add_column("Trạng thái", justify="center")
    table.add_column("Lịch chạy", style="white")
    table.add_column("Keywords", justify="center")
    table.add_column("Limit", justify="center")
    table.add_column("Lần chạy cuối", style="dim")
    table.add_column("Thời lượng", justify="right")
    table.add_column("Lần chạy tới", style="green")
    table.add_column("Thành công / Tổng", justify="center")

    all_names = sorted(list(jobs_cfg.keys()))
    if not all_names:
        console.print("[dim]Chưa có job nào được cấu hình trong jobs.yaml.[/dim]\n")
        return

    for name in all_names:
        j = jobs_cfg[name]
        state = db.get_job_state(name)
        
        # Schedule label
        sched = j.schedule
        if "every" in sched:
            sched_label = f"every {sched['every']}"
        elif "cron" in sched:
            sched_label = f"cron '{sched['cron']}'"
        else:
            sched_label = "Chưa đặt"

        if not j.enabled:
            status_badge = "[dim]⏸ Tắt[/dim]"
        elif state and state.get("last_status") == "RUNNING":
            status_badge = "[bold green]🟢 Đang chạy[/bold green]"
        elif state and state.get("last_status") == "SUCCESS":
            status_badge = "[bold green]✅ Thành công[/bold green]"
        elif state and state.get("last_status") in ("FAILED", "INTERRUPTED"):
            status_badge = f"[bold red]🔴 Lỗi ({state['last_status']})[/bold red]"
        elif state and state.get("last_status") == "PARTIAL":
            status_badge = "[bold yellow]🟡 Một phần[/bold yellow]"
        else:
            status_badge = "[dim]⏳ Chờ chạy[/dim]"

        kw_count = str(len(j.keywords))
        lim_str = str(j.limit) if j.limit else "∞"

        last_run_str = "-"
        duration_str = "-"
        if state and state.get("last_run_id"):
            last_run = db.get_run(state["last_run_id"])
            if last_run:
                last_run_str = format_relative_time(last_run["started_at"])
                if last_run.get("duration_sec"):
                    duration_str = f"{last_run['duration_sec']}s"

        next_run_val = state.get("next_run_at") if state else None
        if not next_run_val and j.enabled:
            next_dt, _ = calculate_next_run(j.schedule)
            if next_dt:
                next_run_val = next_dt.isoformat()

        next_run_str = format_relative_time(next_run_val) if (next_run_val and j.enabled) else "-"

        total_runs = state.get("total_runs", 0) if state else 0
        total_fails = state.get("total_failures", 0) if state else 0
        total_ok = max(0, total_runs - total_fails)
        stats_str = f"{total_ok}/{total_runs}" if total_runs > 0 else "0/0"

        job_display = f"{name}"
        if getattr(j, "itravels_type", None):
            job_display += f"\n[dim magenta]API: {j.itravels_type}[/dim magenta]"

        table.add_row(
            job_display,
            status_badge,
            sched_label,
            kw_count,
            lim_str,
            last_run_str,
            duration_str,
            next_run_str,
            stats_str,
        )

    console.print(table)
    console.print("")


# -----------------------------------------------------------------------------
# COMMAND: errors
# -----------------------------------------------------------------------------
def cmd_errors(args):
    db = SchedulerDB(DEFAULT_DB_PATH)
    failed_runs = db.get_failed_runs(limit=args.limit)

    if not failed_runs:
        console.print("[bold green]✔ Tuyệt vời! Không có tác vụ nào gặp lỗi gần đây.[/bold green]\n")
        return

    table = Table(
        title=f"Lịch sử {len(failed_runs)} lần chạy thất bại gần nhất",
        show_header=True,
        header_style="bold red",
        show_lines=True,
    )
    table.add_column("Run ID", justify="right", style="dim", no_wrap=True)
    table.add_column("Tên Job", style="cyan", no_wrap=True)
    table.add_column("Trạng thái", justify="center")
    table.add_column("Thời gian", style="white")
    table.add_column("Keywords Lỗi", justify="center")
    table.add_column("Tóm tắt lỗi", style="yellow")
    table.add_column("File Log", style="dim")

    for r in failed_runs:
        st_color = "red" if r["status"] == "FAILED" else "yellow"
        st_badge = f"[{st_color}]{r['status']}[/{st_color}]"
        
        kw_stat = f"{r.get('keywords_failed', 0)}/{r.get('keywords_total', 0)}"
        time_str = r.get("finished_at") or r.get("started_at") or "-"
        time_formatted = format_relative_time(time_str)
        err_msg = r.get("error_summary") or "Không có chi tiết lỗi"
        if len(err_msg) > 60:
            err_msg = err_msg[:57] + "..."

        log_path = r.get("log_file") or f"logs/{r['job_name']}.log"

        table.add_row(
            str(r["id"]),
            r["job_name"],
            st_badge,
            time_formatted,
            kw_stat,
            err_msg,
            log_path,
        )

    console.print(table)
    console.print("[dim]Mẹo debug: Gõ `python cron.py logs <job_name>` để đọc toàn bộ log chi tiết.[/dim]\n")


# -----------------------------------------------------------------------------
# COMMAND: logs
# -----------------------------------------------------------------------------
def cmd_logs(args):
    job_name = args.job
    log_file = os.path.join(LOGS_DIR, f"{job_name}.log")

    if not os.path.exists(log_file):
        # Kiểm tra daemon.log nếu người dùng không chỉ định hoặc gõ daemon
        if job_name in ("daemon", "system"):
            log_file = os.path.join(LOGS_DIR, "daemon.log")
        
        if not os.path.exists(log_file):
            console.print(f"[bold red]Chưa tìm thấy file log tại:[/bold red] {log_file}")
            console.print("[dim]Hãy chắc chắn job đã từng được chạy ít nhất một lần.[/dim]\n")
            return

    console.print(Panel(
        f"Đang hiển thị {args.tail} dòng cuối cùng của: [cyan]{log_file}[/cyan]",
        title=f"[bold cyan]Log Debug - {job_name}[/bold cyan]",
        border_style="cyan",
    ))

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            tail_lines = lines[-args.tail:] if len(lines) > args.tail else lines
            for line in tail_lines:
                line_str = line.rstrip()
                if "[ERROR]" in line_str:
                    console.print(f"[bold red]{line_str}[/bold red]")
                elif "[WARNING]" in line_str:
                    console.print(f"[bold yellow]{line_str}[/bold yellow]")
                elif "=== Hoàn thành" in line_str or "=== Bắt đầu" in line_str:
                    console.print(f"[bold green]{line_str}[/bold green]")
                else:
                    console.print(line_str)
    except Exception as e:
        console.print(f"[bold red]Lỗi đọc file log:[/bold red] {e}")


# -----------------------------------------------------------------------------
# COMMAND: run / crawl
# -----------------------------------------------------------------------------
def cmd_run(args):
    engine = SchedulerEngine(args.config, console=console)
    jobs_cfg, errors = load_and_validate_config(args.config)
    if errors:
        console.print(f"[bold red]✖ Lỗi cấu hình file '{args.config}':[/bold red]")
        for e in errors:
            console.print(f"  [red]- {e}[/red]")
        sys.exit(1)

    jobs_arg = getattr(args, "jobs", []) or []
    run_all = getattr(args, "all", False) or "all" in jobs_arg or not jobs_arg

    if run_all:
        target_jobs = [name for name, j in jobs_cfg.items() if j.enabled]
        if not target_jobs:
            console.print("[yellow]Không có job nào đang được bật (enabled: true) để chạy.[/yellow]")
            return
    else:
        target_jobs = []
        for name in jobs_arg:
            if name in jobs_cfg:
                target_jobs.append(name)
            else:
                console.print(f"[bold red]Cảnh báo: Không tìm thấy job '{name}' trong file {args.config}[/bold red]")

        if not target_jobs:
            console.print("[bold red]Không có job hợp lệ nào được chọn để chạy.[/bold red]")
            return

    limit_desc = f"\n• Giới hạn tạm thời: [yellow]{args.limit} địa điểm/keyword[/yellow]" if args.limit else ""
    mode_desc = "\n• Chế độ: [magenta]Headed (hiện trình duyệt)[/magenta]" if args.headed else ""

    console.print(Panel(
        f"[bold cyan]Danh sách task cào ngay lập tức tuần tự ({len(target_jobs)} task):[/bold cyan]\n"
        f"[yellow]{', '.join(target_jobs)}[/yellow]"
        f"{limit_desc}{mode_desc}",
        title="[bold green]🚀 Cào Dữ Liệu Ngay Lập Tức (Run Now)[/bold green]",
        border_style="green",
    ))

    results = asyncio.run(engine.run_jobs(
        target_jobs,
        limit_override=args.limit,
        headed=args.headed,
    ))

    # Bảng tóm tắt kết quả
    table = Table(title="Kết Quả Thực Thi Ngay", show_lines=True)
    table.add_column("Tên Task", style="cyan")
    table.add_column("Kết quả", justify="center")
    for name, success in results.items():
        st_txt = "[bold green]Thành công ✅[/bold green]" if success else "[bold red]Lỗi hoặc một phần 🔴[/bold red]"
        table.add_row(name, st_txt)
    console.print(table)
    console.print("[dim]Chạy `./cron.py status` hoặc `./cron.py logs <job_name>` để xem chi tiết log.[/dim]\n")


# -----------------------------------------------------------------------------
# COMMAND: sync
# -----------------------------------------------------------------------------
def cmd_sync(args):
    from src.itravels_sync import ITravelsClient, DEFAULT_BASE_URL, DEFAULT_SITE
    from sync_itravels import find_latest_json_files

    jobs_cfg, errors = load_and_validate_config(args.config)
    if errors:
        console.print(f"[bold red]✖ Lỗi cấu hình file '{args.config}':[/bold red]")
        for e in errors:
            console.print(f"  [red]- {e}[/red]")
        sys.exit(1)

    global_settings = get_global_settings()
    itravels_cfg = global_settings.get("itravels_api") or global_settings.get("itravels", {})

    jobs_arg = getattr(args, "jobs", []) or []
    if not jobs_arg or "all" in jobs_arg or getattr(args, "all", False):
        target_jobs = [name for name, j in jobs_cfg.items() if getattr(j, "itravels_type", None)]
    else:
        target_jobs = [name for name in jobs_arg if name in jobs_cfg and getattr(jobs_cfg[name], "itravels_type", None)]

    if not target_jobs:
        console.print("[yellow]Không tìm thấy job nào có cấu hình 'itravels_type' để đồng bộ.[/yellow]")
        return

    apply_val = 0 if args.dry_run else itravels_cfg.get("apply", 1)
    client = ITravelsClient(
        api_key=itravels_cfg.get("api_key"),
        base_url=itravels_cfg.get("base_url", DEFAULT_BASE_URL),
        site=itravels_cfg.get("site", DEFAULT_SITE),
        apply=apply_val,
        batch_size=itravels_cfg.get("batch_size", 200),
    )

    mode_txt = "[yellow]Dry-run (kiểm tra thử, apply=0)[/yellow]" if args.dry_run else "[bold green]Thực tế (apply=1)[/bold green]"
    console.print(Panel(
        f"[bold cyan]Đồng bộ dữ liệu của {len(target_jobs)} job lên iTravels API:[/bold cyan]\n"
        f"[yellow]{', '.join(target_jobs)}[/yellow]\n"
        f"• Chế độ: {mode_txt}\n"
        f"• Tỉnh/Thành: [cyan]{itravels_cfg.get('site', DEFAULT_SITE)}[/cyan]",
        title="[bold green]📡 Đồng Bộ Dữ Liệu Lên iTravels API[/bold green]",
        border_style="green",
    ))

    for job_name in target_jobs:
        job_obj = jobs_cfg[job_name]
        files = find_latest_json_files(job_name, getattr(job_obj, "data_dir", "data"))
        if not files:
            console.print(f"[yellow]⚠️ Job '{job_name}': Chưa có file JSON kết quả nào trong data/{job_name}/[/yellow]")
            continue

        latest_file = files[0]
        console.print(f"\n[bold cyan]▶ Đồng bộ job '{job_name}' ([yellow]{job_obj.itravels_type}[/yellow]):[/bold cyan] [dim]{latest_file}[/dim]")
        ok, msg, stats = client.sync_file(latest_file, job_obj.itravels_type, dry_run=args.dry_run)
        if ok:
            console.print(f"  [bold green]✔ {msg}[/bold green]")
        else:
            console.print(f"  [bold red]✖ {msg}[/bold red]")


# -----------------------------------------------------------------------------
# COMMAND: cleanup / clean
# -----------------------------------------------------------------------------
def cmd_cleanup(args):
    import glob
    jobs_cfg, _ = load_and_validate_config(args.config)

    deleted_files = []
    freed_bytes = 0

    target_jobs = [args.job] if getattr(args, "job", None) else list(jobs_cfg.keys())

    for job_name in target_jobs:
        job_dir = os.path.join("data", job_name)
        if not os.path.exists(job_dir):
            continue

        files = glob.glob(os.path.join(job_dir, "*.json"))
        if len(files) <= 1:
            continue

        # Sắp xếp file theo mtime giảm dần (mới nhất đầu tiên)
        files.sort(key=os.path.getmtime, reverse=True)
        # Giữ lại 1 file mới nhất
        old_files = files[1:]

        for old_f in old_files:
            try:
                sz = os.path.getsize(old_f)
                os.remove(old_f)
                deleted_files.append((job_name, os.path.basename(old_f), sz))
                freed_bytes += sz
            except Exception as e:
                console.print(f"[red]Lỗi xoá {old_f}: {e}[/red]")

    if not deleted_files:
        console.print("[bold green]✔ Dữ liệu hoàn toàn sạch sẽ! Không có file JSON cũ nào cần dọn dẹp.[/bold green]\n")
        return

    table = Table(title="Danh Sách File Cũ Đã Dọn Rác", show_lines=True)
    table.add_column("Tên Job", style="cyan")
    table.add_column("File đã xoá", style="yellow")
    table.add_column("Dung lượng giải phóng", justify="right")

    for jname, bname, sz in deleted_files:
        sz_kb = sz / 1024
        table.add_row(jname, bname, f"{sz_kb:.1f} KB")

    console.print(table)
    console.print(f"[bold green]✔ Đã dọn dẹp thành công {len(deleted_files)} file cũ (Giải phóng {freed_bytes / 1024:.1f} KB).[/bold green]\n")


# -----------------------------------------------------------------------------
# COMMAND: validate
# -----------------------------------------------------------------------------
def cmd_validate(args):
    jobs, errors = load_and_validate_config(args.config)
    if errors:
        console.print(f"[bold red]✖ Cấu hình '{args.config}' có {len(errors)} lỗi:[/bold red]")
        for e in errors:
            console.print(f"  [red]- {e}[/red]")
        sys.exit(1)
    else:
        console.print(f"[bold green]✔ File cấu hình '{args.config}' hoàn toàn hợp lệ![/bold green]")
        console.print(f"Tổng số jobs: [cyan]{len(jobs)}[/cyan]")
        for name, j in jobs.items():
            status_txt = "[green]Bật[/green]" if j.enabled else "[dim]Tắt[/dim]"
            sched_txt = f"every {j.schedule.get('every')}" if 'every' in j.schedule else f"cron '{j.schedule.get('cron')}'"
            console.print(f"  • [cyan]{name}[/cyan] ({status_txt}): {len(j.keywords)} keywords, lịch: {sched_txt}, limit: {j.limit or 'all'}")
        console.print("")


# -----------------------------------------------------------------------------
# COMMAND: start
# -----------------------------------------------------------------------------
def cmd_start(args):
    current_pid = os.getpid()
    pid = get_daemon_pid()
    if pid and pid != current_pid:
        console.print(f"[bold yellow]⚠️ Scheduler Daemon đã đang chạy với PID {pid}.[/bold yellow]")
        console.print("[dim]Dùng `python cron.py stop` nếu muốn dừng hoặc khởi động lại.[/dim]\n")
        return

    # Kiểm tra tính hợp lệ của file config trước khi start
    _, errors = load_and_validate_config(args.config)
    if errors:
        console.print(f"[bold red]✖ Không thể khởi động do file '{args.config}' có lỗi:[/bold red]")
        for e in errors:
            console.print(f"  [red]- {e}[/red]")
        sys.exit(1)

    run_immediately = not getattr(args, "wait_schedule", False)

    if args.daemon:
        # Chạy ở chế độ background daemon
        os.makedirs("data", exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        daemon_log_path = os.path.join(LOGS_DIR, "daemon.log")

        start_cmd = [sys.executable, os.path.abspath(__file__), "--config", args.config, "start"]
        if getattr(args, "wait_schedule", False):
            start_cmd.append("--wait-schedule")

        # Khởi chạy sub-process tách biệt
        daemon_log_file = open(daemon_log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            start_cmd,
            stdout=daemon_log_file,
            stderr=daemon_log_file,
            start_new_session=True,
        )

        with open(PID_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))

        init_note = " (sẽ cào ngay lập tức lần lượt các task đợt đầu)" if run_immediately else ""
        console.print(Panel(
            f"[bold green]✔ Scheduler Daemon đã được khởi chạy ngầm thành công!{init_note}[/bold green]\n"
            f"• PID: [cyan]{proc.pid}[/cyan]\n"
            f"• File log daemon: [dim]{daemon_log_path}[/dim]\n"
            f"• Kiểm tra trạng thái: [yellow]./cron.py status[/yellow]\n"
            f"• Dừng daemon: [yellow]./cron.py stop[/yellow]",
            title="[bold green]Background Daemon Started[/bold green]",
            border_style="green",
        ))
    else:
        # Chạy ở chế độ Foreground
        os.makedirs("data", exist_ok=True)
        with open(PID_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

        init_note = "\n• [bold green]Chế độ:[/bold green] Cào ngay lập tức tuần tự các task đợt đầu, sau đó lặp định kỳ theo lịch." if run_immediately else ""
        console.print(Panel(
            f"[bold green]✔ Scheduler đang chạy ở chế độ Foreground[/bold green] (PID: [cyan]{os.getpid()}[/cyan])"
            f"{init_note}\n"
            f"• Nhấn [bold red]Ctrl + C[/bold red] để dừng tiến trình an toàn.\n"
            f"• Hệ thống hỗ trợ Hot-reload: Bạn có thể sửa '{args.config}' bất kỳ lúc nào.",
            title="[bold cyan]Google Maps Scheduler Active[/bold cyan]",
            border_style="cyan",
        ))

        engine = SchedulerEngine(args.config, console=console)

        def handle_signal(sig, frame):
            console.print("\n[yellow]Đang thực hiện dừng an toàn Scheduler Engine...[/yellow]")
            engine.is_running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            asyncio.run(engine.scheduler_loop(run_immediately=run_immediately))
        finally:
            if os.path.exists(PID_FILE_PATH):
                try:
                    os.remove(PID_FILE_PATH)
                except OSError:
                    pass
            console.print("[bold green]✔ Đã dừng an toàn Scheduler.[/bold green]\n")


# -----------------------------------------------------------------------------
# COMMAND: stop
# -----------------------------------------------------------------------------
def cmd_stop(args):
    pid = get_daemon_pid()
    if not pid:
        console.print("[yellow]Không tìm thấy tiến trình Scheduler Daemon nào đang chạy.[/yellow]\n")
        return

    console.print(f"[yellow]Đang gửi tín hiệu dừng tới Daemon (PID: {pid})...[/yellow]")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.5)
            if not is_process_alive(pid):
                break
        
        if is_process_alive(pid):
            console.print("[yellow]Tiến trình chưa dừng, đang ép buộc tắt...[/yellow]")
            os.kill(pid, signal.SIGKILL)

        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)

        console.print(f"[bold green]✔ Đã dừng hoàn toàn Scheduler Daemon (PID: {pid}).[/bold green]\n")
    except Exception as e:
        console.print(f"[bold red]Lỗi khi dừng daemon:[/bold red] {e}\n")


# -----------------------------------------------------------------------------
# COMMAND: install-service
# -----------------------------------------------------------------------------
def cmd_install_service(args):
    project_dir = os.path.abspath(".")
    venv_python = os.path.abspath(sys.executable)
    user = os.environ.get("USER", "root")

    service_content = f"""[Unit]
Description=Google Maps Places Scraper Scheduled Service
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={project_dir}
ExecStart={venv_python} cron.py start
Restart=always
RestartSec=10
StandardOutput=append:{project_dir}/logs/daemon.log
StandardError=append:{project_dir}/logs/daemon.log

[Install]
WantedBy=multi-user.target
"""
    service_file = "googlemaps-cron.service"
    with open(service_file, "w", encoding="utf-8") as f:
        f.write(service_content)

    console.print(Panel(
        f"[bold green]✔ Đã tạo file service mẫu:[/bold green] [cyan]{service_file}[/cyan]\n\n"
        f"Để kích hoạt tự chạy cùng hệ thống Linux (systemd):\n"
        f"1. [yellow]sudo cp {service_file} /etc/systemd/system/[/yellow]\n"
        f"2. [yellow]sudo systemctl daemon-reload[/yellow]\n"
        f"3. [yellow]sudo systemctl enable --now googlemaps-cron[/yellow]\n"
        f"4. Kiểm tra: [yellow]sudo systemctl status googlemaps-cron[/yellow]",
        title="[bold green]Systemd Service Setup[/bold green]",
        border_style="green",
    ))


# -----------------------------------------------------------------------------
# MAIN CLI DISPATCHER
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Google Maps Recurring Scheduler & Cronjob Manager CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="Đường dẫn file cấu hình YAML (mặc định: jobs.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Lệnh thực hiện")

    # status
    p_status = subparsers.add_parser("status", help="Xem bảng trạng thái realtime các cronjob")

    # errors
    p_errors = subparsers.add_parser("errors", help="Xem danh sách các lần chạy bị lỗi gần nhất")
    p_errors.add_argument("-l", "--limit", type=int, default=15, help="Số lượng lỗi hiển thị (mặc định: 15)")

    # logs
    p_logs = subparsers.add_parser("logs", help="Xem log debug chi tiết của một job")
    p_logs.add_argument("job", help="Tên job cần xem log (hoặc 'daemon')")
    p_logs.add_argument("-n", "--tail", type=int, default=50, help="Số dòng cuối cùng cần xem (mặc định: 50)")

    # run / crawl
    p_run = subparsers.add_parser(
        "run", aliases=["crawl"], help="Cào ngay lập tức 1 hoặc nhiều task (hoặc tất cả các task)"
    )
    p_run.add_argument(
        "jobs",
        nargs="*",
        help="Tên các job cần chạy ngay (để trống hoặc 'all' để chạy lần lượt tất cả các task)",
    )
    p_run.add_argument("-a", "--all", action="store_true", help="Cào lần lượt tất cả các task đang bật")
    p_run.add_argument(
        "-l", "--limit", type=int, default=None, help="Tùy chọn giới hạn số địa điểm (ví dụ: -l 2 để test nhanh)"
    )
    p_run.add_argument("--headed", action="store_true", help="Hiển thị cửa sổ trình duyệt khi cào")

    # sync
    p_sync = subparsers.add_parser("sync", help="Đồng bộ dữ liệu của job lên iTravels API")
    p_sync.add_argument(
        "jobs", nargs="*", help="Tên các job cần đồng bộ (để trống hoặc 'all' để đồng bộ tất cả)"
    )
    p_sync.add_argument("-a", "--all", action="store_true", help="Đồng bộ tất cả các job có itravels_type")
    p_sync.add_argument(
        "--dry-run", action="store_true", help="Chạy thử kiểm tra (apply=0: chỉ kiểm tra, không lưu)"
    )

    # validate
    p_val = subparsers.add_parser("validate", help="Kiểm tra tính hợp lệ của file jobs.yaml")

    # start
    p_start = subparsers.add_parser(
        "start", help="Khởi động Scheduler (mặc định cào ngay lập tức đợt đầu, sau đó lặp định kỳ)"
    )
    p_start.add_argument("-d", "--daemon", action="store_true", help="Chạy ngầm (Background daemon)")
    p_start.add_argument(
        "--wait-schedule", action="store_true", help="Chỉ chờ chạy theo đúng giờ trong lịch (bỏ qua đợt cào ngay đợt đầu)"
    )

    # stop
    p_stop = subparsers.add_parser("stop", help="Dừng Scheduler Daemon đang chạy ngầm")

    # install-service
    p_svc = subparsers.add_parser("install-service", help="Tạo file cấu hình Linux systemd service")

    # cleanup / clean
    p_clean = subparsers.add_parser(
        "cleanup", aliases=["clean"], help="Dọn dẹp các file JSON kết quả cũ của những lần chạy trước"
    )
    p_clean.add_argument("--job", "-j", help="Chỉ dọn dẹp file cũ của một job cụ thể")

    args = parser.parse_args()

    if not args.command:
        cmd_status(args)
        return

    if args.command == "status":
        cmd_status(args)
    elif args.command == "errors":
        cmd_errors(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command in ("run", "crawl"):
        cmd_run(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "install-service":
        cmd_install_service(args)
    elif args.command in ("cleanup", "clean"):
        cmd_cleanup(args)


if __name__ == "__main__":
    main()
