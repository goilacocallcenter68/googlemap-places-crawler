from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import re
import base64
import struct
from urllib.parse import unquote


def chij_to_hex(chij: str) -> Optional[str]:
    """Chuyển Google Place ID dạng base64 protobuf (ChIJ...) sang dạng hex (0x...:0x...).
    
    Cấu trúc protobuf của Google Place ID:
    - Byte 0: 0x0a (tag 1, wire type 2 length-delimited)
    - Byte 1: độ dài (thường là 0x12 = 18 bytes)
    - Byte 2: 0x09 (tag 1, wire type 1 fixed64)
    - Bytes 3..10: uint64 little-endian (feature namespace)
    - Byte 11: 0x11 (tag 2, wire type 1 fixed64)
    - Bytes 12..19: uint64 little-endian (feature id / CID)
    """
    if not chij or not isinstance(chij, str) or not chij.startswith("ChIJ"):
        return None
    try:
        padded = chij + "=" * ((4 - len(chij) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded)
        if len(raw) >= 20 and raw[0] == 0x0A and raw[2] == 0x09 and raw[11] == 0x11:
            f1 = struct.unpack("<Q", raw[3:11])[0]
            f2 = struct.unpack("<Q", raw[12:20])[0]
            return f"{hex(f1)}:{hex(f2)}"
    except Exception:
        pass
    return None


def parse_place_id_from_url(url: Optional[str]) -> Optional[str]:
    """Trích xuất place_id chuẩn hoá ở định dạng hex (0x...:0x...) từ URL Google Maps.
    
    Luôn ưu tiên định dạng 0x...:0x... (từ !1s hoặc ftid=). Nếu URL chỉ có ChIJ... (từ !19s),
    tự động giải mã protobuf sang 0x...:0x... để đồng nhất tuyệt đối.
    """
    if not url or not isinstance(url, str):
        return None
    url = unquote(url)

    # 1. Ưu tiên cao nhất: trích xuất cặp hex 0x...:0x... trong URL
    match_hex = re.search(r'(?:!1s|ftid=)?(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)', url)
    if match_hex:
        raw_hex = match_hex.group(1)
        parts = raw_hex.split(":")
        return f"{parts[0].lower()}:{parts[1].lower()}"

    # 2. Ưu tiên thứ hai: nếu chỉ có ChIJ..., giải mã base64 protobuf sang hex 0x...:0x...
    match_chij = re.search(r'(?:!19s|[?&]place_id=)?(ChIJ[a-zA-Z0-9_-]+)', url)
    if match_chij:
        chij = match_chij.group(1)
        converted = chij_to_hex(chij)
        if converted:
            return converted
        return chij

    return None


def normalize_place_id(place_id: Optional[str], url: Optional[str] = None) -> Optional[str]:
    """Chuẩn hoá place_id để luôn ở định dạng '0x...:0x...'.
    
    - Nếu là '0x...:0x...': chuẩn hoá về chữ thường (lowercase).
    - Nếu là 'ChIJ...': giải mã base64 protobuf sang '0x...:0x...'.
    - Nếu place_id rỗng nhưng có url: trích xuất từ url.
    """
    if place_id and isinstance(place_id, str):
        place_id = place_id.strip()
        match_hex = re.search(r'^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$', place_id)
        if match_hex:
            parts = place_id.split(":")
            return f"{parts[0].lower()}:{parts[1].lower()}"
        if place_id.startswith("ChIJ"):
            converted = chij_to_hex(place_id)
            if converted:
                return converted
            return place_id

    if url:
        return parse_place_id_from_url(url)

    return place_id


@dataclass
class Review:
    author: str = ""
    author_url: Optional[str] = None
    rating: Optional[float] = None
    publish_date: Optional[str] = None
    content: str = ""
    review_photos: List[str] = field(default_factory=list)
    owner_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class Coordinates:
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MenuItem:
    name: str = ""
    price: Optional[str] = None
    description: Optional[str] = None
    photo: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MenuInfo:
    link: Optional[str] = None
    dishes: List[MenuItem] = field(default_factory=list)
    photos: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class PricePartner:
    partner: str = ""
    price: str = ""
    link: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class PricingInfo:
    main_price: Optional[str] = None
    price_range: Optional[str] = None
    partners: List[PricePartner] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class Place:
    title: str = ""
    place_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    price_range: Optional[str] = None
    pricing: PricingInfo = field(default_factory=PricingInfo)
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    menu: MenuInfo = field(default_factory=MenuInfo)
    booking_link: Optional[str] = None
    plus_code: Optional[str] = None
    opening_hours: Optional[Dict[str, str]] = None
    coordinates: Optional[Coordinates] = None
    about: Dict[str, List[str]] = field(default_factory=dict)
    url: Optional[str] = None
    photos: List[str] = field(default_factory=list)
    reviews: List[Review] = field(default_factory=list)

    def __post_init__(self):
        if self.place_id:
            self.place_id = normalize_place_id(self.place_id, self.url)
        elif self.url:
            self.place_id = parse_place_id_from_url(self.url)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("place_id"):
            d["place_id"] = normalize_place_id(d["place_id"], d.get("url"))
        elif d.get("url"):
            d["place_id"] = parse_place_id_from_url(d["url"])
        return d

