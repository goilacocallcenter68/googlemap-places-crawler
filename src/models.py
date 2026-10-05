from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

