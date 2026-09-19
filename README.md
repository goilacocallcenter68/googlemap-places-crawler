# 🗺️ Google Maps Places & Reviews Crawler

CLI trích xuất toàn diện dữ liệu các địa điểm, nhà hàng, quán ăn từ **Google Maps**, bao gồm:

- **Thông tin chi tiết**: Tên quán, Google Place ID, danh mục/thể loại, đoạn giới thiệu tóm tắt (Description), số sao đánh giá (Rating), tổng số lượt đánh giá, tầm giá, số điện thoại, địa chỉ đầy đủ, mã vị trí (Plus Code), trang web chính thức, link thực đơn (Menu), link đặt bàn / đặt món (Booking / Order), giờ mở cửa theo từng ngày trong tuần, tọa độ địa lý (Latitude, Longitude), URL Google Maps.
- **Tiện nghi & Dịch vụ (About / Giới thiệu)**: Trích xuất toàn diện mọi thuộc tính được phân nhóm: Phù hợp cho người khuyết tật (lối vào cho xe lăn, chỗ ngồi, nhà vệ sinh...), Lựa chọn dịch vụ (ăn tại chỗ, giao hàng gián tiếp, mua hàng trên xe, mang về...), Tiện nghi (Wi-Fi, quầy bar...), Thanh toán (NFC, thẻ tín dụng...), Bầu không khí, Khách hàng, Bãi đỗ xe, Trẻ em, v.v.
- **Đánh giá (Reviews)**: Tên tác giả, sao đánh giá, thời gian đăng, nội dung nhận xét chi tiết, và link các hình ảnh đính kèm trong bài đánh giá.

---

## 📂 Cấu trúc thư mục

```text
googlemap-places/
├── .venv/                   # Môi trường ảo Python (đã cài đặt đầy đủ Playwright & dependencies)
├── browser_profile/         # Profile trình duyệt Chromium lưu cookie & phiên
├── data/                    # Thư mục lưu trữ các file JSON kết quả cào
│   └── quan_ca_phe_ho_con_rua_20260919_113756.json
├── src/
│   ├── __init__.py
│   ├── models.py            # Khai báo dữ liệu Place, Review, Coordinates
│   ├── scraper.py           # Engine điều khiển Playwright cào Google Maps
│   └── ui.py                # Bảng tóm tắt, banner và preview JSON với Rich
├── main.py                  # Entrypoint chính của ứng dụng CLI
├── requirements.txt         # Thư viện phụ thuộc
└── README.md                # Tài liệu hướng dẫn sử dụng
```

---

## 🛠️ Cài đặt & Khởi chạy

### 1. Kích hoạt môi trường (hoặc dùng trực tiếp `.venv/bin/python`)

```bash
# Kích hoạt venv
source .venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt
playwright install chromium
```

### 2. Chạy ứng dụng

Chạy mặc định (headless):

```bash
./.venv/bin/python main.py
```

Chạy chế độ Debug (mở giao diện trình duyệt thật, xem trước demo JSON, hỏi xác nhận trước khi lưu):

```bash
./.venv/bin/python main.py --debug
# hoặc viết tắt
./.venv/bin/python main.py -d
```

Hoặc chỉ bật cửa sổ trình duyệt (headed):

```bash
./.venv/bin/python main.py --headed
```

Tùy chỉnh số tab cào đồng thời (mặc định 4 tab, kiến nghị từ 2 - 6):

```bash
./.venv/bin/python main.py -c 5
```

Giới hạn số lượng địa điểm cào (ví dụ: chỉ lấy 5 quán để test nhanh):

```bash
./.venv/bin/python main.py -l 5
```

Cào bài đánh giá (Reviews):

- **Mặc định**: Lấy tối đa **100 đánh giá/địa điểm**, tự động sắp xếp theo **"Phù hợp nhất"**.
- **Cào toàn bộ (không giới hạn)**: Sử dụng cờ `--all-reviews` hoặc `-r all` / `-r 0`:

  ```bash
  ./.venv/bin/python main.py --all-reviews
  # hoặc
  ./.venv/bin/python main.py -r all
  ```

- **Tùy chỉnh số lượng đánh giá tối đa** (ví dụ: 30 bài đánh giá mỗi địa điểm):

  ```bash
  ./.venv/bin/python main.py -r 30
  ```

- **Chọn tiêu chí lọc bài đánh giá** (`-s / --sort`):
  - `most_relevant` (hoặc `relevant`): Phù hợp nhất (mặc định)
  - `newest`: Mới nhất
  - `highest_rating` (hoặc `highest`): Đánh giá cao nhất
  - `lowest_rating` (hoặc `lowest`): Đánh giá thấp nhất

  ```bash
  ./.venv/bin/python main.py -s newest
  ```

_Mẹo: Có thể truyền cờ tùy chỉnh trực tiếp ngay trong khung tìm kiếm tương tác khi app đang chạy, ví dụ:_

- `cà phê quận 1 -l 3 -r 20` (lấy 3 quán, mỗi quán 20 review)
- `bún chả hà nội --all-reviews` (cào toàn bộ review)
- `khách sạn đà nẵng -r all -s newest` (cào toàn bộ review sắp xếp mới nhất)

Tùy chỉnh thư mục lưu kết quả:

```bash
./.venv/bin/python main.py --data-dir my_exports
```

---

## 📄 Cấu trúc dữ liệu JSON xuất ra

```json
[
  {
    "title": "Phê La - Hồ Con Rùa",
    "place_id": "ChIJbXz85goudTERkZgB1cW...",
    "category": "Quán cà phê",
    "description": "Quán cà phê phong cách hiện đại với không gian ngoài trời thoáng đãng...",
    "rating": 4.3,
    "reviews_count": 1166,
    "price_range": null,
    "address": "Số 6, Trần Cao Vân/Công trường Quốc Tế/42 Hồ Con Rùa, Quận 3, Hồ Chí Minh, Việt Nam",
    "phone": "+84 1900 3013",
    "website": "https://phela.vn/",
    "menu": "https://phela.vn/menu",
    "booking_link": null,
    "plus_code": "QMHX+7C Quận 3, Hồ Chí Minh, Việt Nam",
    "opening_hours": {
      "Thứ Bảy": "07:00–22:00",
      "Chủ Nhật": "07:00–22:00",
      "Thứ Hai": "07:00–22:00",
      "Thứ Ba": "07:00–22:00",
      "Thứ Tư": "07:00–22:00",
      "Thứ Năm": "07:00–22:00",
      "Thứ Sáu": "07:00–22:00"
    },
    "coordinates": {
      "latitude": 10.7831855,
      "longitude": 106.695983
    },
    "about": {
      "Phù hợp cho người khuyết tật": [
        "Lối vào cho xe lăn",
        "Chỗ ngồi cho xe lăn",
        "Nhà vệ sinh cho xe lăn"
      ],
      "Các tùy chọn dịch vụ": [
        "Ăn tại chỗ",
        "Đồ ăn mang đi",
        "Giao hàng gián tiếp"
      ],
      "Tiện nghi": [
        "Wi-Fi",
        "Wi-Fi miễn phí",
        "Nhà vệ sinh"
      ],
      "Thanh toán": [
        "Thanh toán di động qua NFC",
        "Thẻ tín dụng"
      ]
    },
    "url": "https://www.google.com/maps/place/...",
    "photos": ["https://lh3.googleusercontent.com/...=s1600"],
    "reviews": [
      {
        "author": "Cuong Cao",
        "author_url": "https://www.google.com/maps/contrib/...",
        "rating": 5.0,
        "publish_date": "2 tháng trước",
        "content": "Phê La ở đây không gian đẹp...",
        "review_photos": ["https://lh3.googleusercontent.com/...=s1600"],
        "owner_response": null
      }
    ]
  }
]
```
