import json
import os
from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from src.models import Place

console = Console()

def print_banner():
    banner_text = Text()
    banner_text.append("🗺️  GOOGLE MAPS PLACES & REVIEWS CRAWLER  🗺️\n", style="bold cyan")
    banner_text.append("Thu thập tự động dữ liệu nhà hàng, quán ăn, đánh giá & hình ảnh\n", style="italic white")
    banner_text.append("Nhập 'exit' hoặc 'q' để thoát bất kỳ lúc nào.", style="dim yellow")
    
    panel = Panel(banner_text, border_style="cyan", expand=False)
    console.print(panel)
    console.print()

def print_summary_table(places: List[Place], keyword: str):
    if not places:
        console.print(Panel(f"[yellow]⚠️  Không tìm thấy nhà hàng/địa điểm nào cho từ khóa: [bold]{keyword}[/bold][/yellow]", border_style="yellow"))
        return

    table = Table(
        title=f"📊 KẾT QUẢ TÌM KIẾM CHO: '{keyword.upper()}' (Tổng: {len(places)} địa điểm)",
        title_style="bold green",
        header_style="bold magenta",
        show_lines=True
    )

    table.add_column("#", justify="center", style="bold cyan", width=4)
    table.add_column("Tên địa điểm / Quán", style="bold white", width=24)
    table.add_column("Danh mục", style="green", width=15)
    table.add_column("⭐ Đánh giá", justify="center", style="yellow", width=12)
    table.add_column("Khoảng giá", justify="center", style="bold yellow", width=18)
    table.add_column("Số ĐT", style="cyan", width=14)
    table.add_column("Địa chỉ", style="white", width=28)
    table.add_column("Reviews cào", justify="center", style="magenta", width=11)
    table.add_column("Ảnh", justify="center", style="blue", width=7)
    table.add_column("Thực đơn", justify="center", style="bold green", width=16)
    table.add_column("Tiện ích/About", justify="center", style="green", width=14)

    for i, p in enumerate(places, 1):
        rating_str = f"{p.rating:.1f} ({p.reviews_count or 0})" if p.rating else "N/A"

        # Format price column
        price_str = "N/A"
        if p.pricing and (p.pricing.main_price or p.pricing.partners):
            base_p = p.pricing.main_price or (p.pricing.partners[0].price if p.pricing.partners else "")
            partner_cnt = len(p.pricing.partners)
            if partner_cnt > 0:
                price_str = f"{base_p} ({partner_cnt} ĐT)"
            else:
                price_str = base_p or "N/A"
        elif p.price_range:
            price_str = p.price_range

        addr = (p.address[:25] + "...") if p.address and len(p.address) > 28 else (p.address or "N/A")
        title = (p.title[:21] + "...") if len(p.title) > 24 else p.title
        phone = p.phone or "N/A"
        cat = p.category or "N/A"
        rev_count = str(len(p.reviews))
        photo_count = str(len(p.photos))
        about_count = sum(len(v) for v in p.about.values()) if p.about else 0
        about_str = f"{about_count} mục" if about_count > 0 else "0"

        # Format menu column
        menu_desc = "-"
        if p.menu:
            parts = []
            if p.menu.link:
                parts.append("Link")
            if p.menu.dishes:
                parts.append(f"{len(p.menu.dishes)} món")
            if p.menu.photos:
                parts.append(f"{len(p.menu.photos)} ảnh")
            menu_desc = " · ".join(parts) if parts else "-"

        table.add_row(
            str(i),
            title,
            cat,
            rating_str,
            price_str,
            phone,
            addr,
            rev_count,
            photo_count,
            menu_desc,
            about_str
        )

    console.print(table)
    console.print()

def print_demo_json(places: List[Place]):
    if not places:
        console.print("[dim]Dữ liệu demo rỗng: [][][/dim]")
        return

    first_place = places[0].to_dict()
    # If there are many reviews or photos, keep demo preview readable
    demo_copy = json.loads(json.dumps(first_place, ensure_ascii=False))
    if len(demo_copy.get("reviews", [])) > 2:
        demo_copy["reviews"] = demo_copy["reviews"][:2]
        demo_copy["_note"] = f"... và {len(places[0].reviews) - 2} đánh giá khác"
    if len(demo_copy.get("photos", [])) > 3:
        demo_copy["photos"] = demo_copy["photos"][:3] + [f"... còn {len(places[0].photos) - 3} ảnh nữa"]
    if "pricing" in demo_copy and isinstance(demo_copy["pricing"], dict):
        partners_list = demo_copy["pricing"].get("partners", [])
        if len(partners_list) > 2:
            demo_copy["pricing"]["partners"] = partners_list[:2] + [{"_note": f"... còn {len(partners_list) - 2} đối tác đặt phòng khác"}]
    if "menu" in demo_copy and isinstance(demo_copy["menu"], dict):
        dishes_list = demo_copy["menu"].get("dishes", [])
        if len(dishes_list) > 3:
            demo_copy["menu"]["dishes"] = dishes_list[:3] + [{"_note": f"... còn {len(dishes_list) - 3} món nữa"}]
        menu_photos = demo_copy["menu"].get("photos", [])
        if len(menu_photos) > 2:
            demo_copy["menu"]["photos"] = menu_photos[:2] + [f"... còn {len(menu_photos) - 2} ảnh thực đơn nữa"]

    json_str = json.dumps([demo_copy], indent=2, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
    
    panel = Panel(
        syntax,
        title=f"[bold cyan]🔍 DEMO DỮ LIỆU JSON (Mẫu: {places[0].title})[/bold cyan]",
        border_style="cyan"
    )
    console.print(panel)
    console.print()
