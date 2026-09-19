import argparse
import asyncio
import datetime
import json
import os
import re
import sys
from slugify import slugify
from rich.console import Console
from rich.prompt import Confirm
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeRemainingColumn,
)

from src.models import Place
from src.scraper import GoogleMapsScraper
from src.ui import print_banner, print_summary_table, print_demo_json

console = Console()

def save_results_to_json(places: list[Place], keyword: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    slug = slugify(keyword, separator="_") if keyword else "places"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.json"
    file_path = os.path.join(output_dir, filename)

    data = [p.to_dict() for p in places]
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path

SORT_LABELS = {
    "most_relevant": "Phù hợp nhất",
    "relevant": "Phù hợp nhất",
    "newest": "Mới nhất",
    "highest_rating": "Xếp hạng cao nhất",
    "highest": "Xếp hạng cao nhất",
    "lowest_rating": "Xếp hạng thấp nhất",
    "lowest": "Xếp hạng thấp nhất",
}

def parse_review_limit(val, all_flag: bool = False) -> int:
    if all_flag:
        return 0  # 0 indicates unlimited
    if val is None:
        return 100
    s = str(val).strip().lower()
    if s in ("all", "none", "0", "unlimited", "full", "tat_ca"):
        return 0
    try:
        n = int(s)
        return max(0, n)
    except ValueError:
        return 100

async def run_cli(args):
    print_banner()

    is_headed = args.debug or args.headed
    user_data_dir = os.path.abspath(args.profile_dir) if args.profile_dir else None
    scraper = GoogleMapsScraper(
        headless=not is_headed,
        user_data_dir=user_data_dir,
        concurrency=args.concurrency
    )

    mode_label = "Debug - Headed" if args.debug else ("Headed" if is_headed else "Headless")
    console.print(f"[dim]🚀 Đang khởi động trình duyệt ({mode_label})...[/dim]")
    await scraper.start()
    console.print("[bold green]✔ Trình duyệt đã sẵn sàng![/bold green]\n")

    try:
        while True:
            try:
                keyword = console.input("[bold green]🔍 Nhập từ khóa tìm kiếm (hoặc 'exit' để thoát): [/bold green]").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Thoát ứng dụng.[/yellow]")
                break

            if not keyword:
                continue

            if keyword.lower() in ("exit", "quit", "q"):
                console.print("[yellow]Cảm ơn bạn đã sử dụng app. Tạm biệt![/yellow]")
                break

            # Support inline limit override in keyword prompt, e.g. "cà phê quận 1 -l 3 -r 20"
            current_limit = args.limit
            match_limit = re.search(r'(?:--limit|-l)\s+(\d+)', keyword)
            if match_limit:
                current_limit = int(match_limit.group(1))
                keyword = re.sub(r'(?:--limit|-l)\s+(\d+)', '', keyword).strip()

            current_all_reviews = args.all_reviews
            if "--all-reviews" in keyword:
                current_all_reviews = True
                keyword = keyword.replace("--all-reviews", "").strip()

            current_max_reviews = args.max_reviews
            match_rev = re.search(r'(?:--max-reviews|-r)\s+(\S+)', keyword)
            if match_rev:
                current_max_reviews = match_rev.group(1)
                keyword = re.sub(r'(?:--max-reviews|-r)\s+(\S+)', '', keyword).strip()

            parsed_max_reviews = parse_review_limit(current_max_reviews, current_all_reviews)

            current_sort = args.sort
            match_sort = re.search(r'(?:--sort|-s)\s+(\S+)', keyword)
            if match_sort:
                val_sort = match_sort.group(1).lower()
                if val_sort in SORT_LABELS:
                    current_sort = val_sort
                keyword = re.sub(r'(?:--sort|-s)\s+(\S+)', '', keyword).strip()

            current_debug = args.debug
            match_debug = re.search(r'(?:--debug|-d)\b', keyword)
            if match_debug:
                current_debug = True
                keyword = re.sub(r'(?:--debug|-d)\b', '', keyword).strip()

            limit_info = f", Giới hạn: [yellow]{current_limit} địa điểm[/yellow]" if current_limit else ""
            if parsed_max_reviews == 0:
                rev_info = ", [dim]cào toàn bộ đánh giá (không giới hạn)[/dim]"
            else:
                rev_info = f", [cyan]tối đa {parsed_max_reviews} đánh giá/địa điểm[/cyan]"
            sort_info = f", Lọc: [magenta]{SORT_LABELS.get(current_sort, 'Phù hợp nhất')}[/magenta]"
            debug_info = ", [bold red]Mode Debug[/bold red]" if current_debug else ""

            console.print(f"\n[bold cyan]⏳ Bắt đầu tìm kiếm: [white]'{keyword}'[/white] (Song song: [green]{args.concurrency} luồng[/green]{limit_info}{rev_info}{sort_info}{debug_info})...[/bold cyan]")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=35),
                TaskProgressColumn(),
                MofNCompleteColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) as progress:
                task_id = progress.add_task("Đang kết nối Google Maps...", total=None)

                def on_progress(msg: str, current: int, total: int):
                    if total > 0:
                        short_msg = (msg[:30] + "...") if len(msg) > 33 else msg
                        progress.update(
                            task_id,
                            description=f"[bold green]Cào:[/] [white]{short_msg}[/]",
                            completed=current,
                            total=total
                        )
                    else:
                        progress.update(
                            task_id,
                            description=f"[yellow]{msg}[/yellow]",
                            completed=0,
                            total=None
                        )

                places = await scraper.crawl_keyword(
                    keyword,
                    progress_callback=on_progress,
                    concurrency=args.concurrency,
                    limit=current_limit,
                    max_reviews=parsed_max_reviews,
                    sort_by=current_sort
                )

            # 1. Tóm tắt kết quả ra terminal
            print_summary_table(places, keyword)

            # 2. Xử lý lưu và hiển thị theo mode
            if current_debug:
                # Mode debug: Hiển thị demo JSON và hỏi xác nhận có muốn lưu không
                print_demo_json(places)

                try:
                    save_confirm = console.input("[bold cyan]💾 Bạn có muốn lưu vào file JSON không? [y/N]: [/bold cyan]").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    save_confirm = "n"

                if save_confirm in ("y", "yes"):
                    saved_path = save_results_to_json(places, keyword, args.data_dir)
                    abs_path = os.path.abspath(saved_path)
                    file_size_kb = os.path.getsize(saved_path) / 1024
                    file_url = f"file://{abs_path}"
                    console.print(f"[bold green]✔ Đã lưu thành công {len(places)} địa điểm vào:[/bold green] [underline white]{saved_path}[/underline white] ({file_size_kb:.1f} KB)")
                    console.print(f"[bold green]📂 URL lưu kết quả:[/bold green] [link={file_url}]{file_url}[/link]\n")
                else:
                    console.print("[dim]Bỏ qua lưu file.[/dim]\n")
            else:
                # Mode mặc định: Tự động lưu và chỉ ra URL lưu kết quả
                if places:
                    saved_path = save_results_to_json(places, keyword, args.data_dir)
                    abs_path = os.path.abspath(saved_path)
                    file_size_kb = os.path.getsize(saved_path) / 1024
                    file_url = f"file://{abs_path}"
                    console.print(f"[bold green]✔ Đã lưu {len(places)} địa điểm vào:[/bold green] [underline white]{saved_path}[/underline white] ({file_size_kb:.1f} KB)")
                    console.print(f"[bold green]📂 URL lưu kết quả:[/bold green] [link={file_url}]{file_url}[/link]\n")
                else:
                    console.print("[yellow]⚠️ Không tìm thấy địa điểm nào để lưu kết quả.[/yellow]\n")

    finally:
        console.print("[dim]Đang đóng trình duyệt...[/dim]")
        await scraper.close()
        console.print("[bold green]✔ Đã hoàn tất tắt trình duyệt an toàn.[/bold green]")

def main():
    parser = argparse.ArgumentParser(description="Google Maps Places & Reviews Crawler CLI")
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=4,
        help="Số lượng tab/luồng cào đồng thời (mặc định: 4, kiến nghị: 2-6)"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Giới hạn số lượng địa điểm cần cào (mặc định: cào toàn bộ, ví dụ: -l 5 để test nhanh)"
    )
    parser.add_argument(
        "-r", "--max-reviews",
        default="100",
        help="Giới hạn số lượng bài đánh giá tối đa mỗi địa điểm (mặc định: 100, truyền 'all' hoặc '0' để cào toàn bộ không giới hạn)"
    )
    parser.add_argument(
        "--all-reviews",
        action="store_true",
        help="Bỏ giới hạn số lượng bài đánh giá, cào toàn bộ tất cả bài đánh giá trên Google Maps"
    )
    parser.add_argument(
        "-s", "--sort",
        choices=["most_relevant", "relevant", "newest", "highest_rating", "highest", "lowest_rating", "lowest"],
        default="most_relevant",
        help="Tiêu chí sắp xếp bài đánh giá (mặc định: most_relevant - phù hợp nhất, newest, highest_rating, lowest_rating)"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Chế độ debug: mở trình duyệt có giao diện (headed), hiển thị demo JSON và hỏi xác nhận trước khi lưu file"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Hiển thị cửa sổ trình duyệt khi cào (mặc định chạy ngầm headless)"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Thư mục lưu trữ file JSON kết quả (mặc định: 'data')"
    )
    parser.add_argument(
        "--profile-dir",
        default="browser_profile",
        help="Thư mục lưu session/profile trình duyệt (giữ cookie & đăng nhập)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Chương trình bị ngắt bởi người dùng.[/yellow]")
        sys.exit(0)

if __name__ == "__main__":
    main()
