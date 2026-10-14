# 🗺️ Google Maps Places & Reviews Crawler

CLI trích xuất toàn diện dữ liệu các địa điểm, nhà hàng, quán ăn từ **Google Maps**, bao gồm:

- **Thông tin chi tiết**: Tên quán, Google Place ID, danh mục/thể loại, đoạn giới thiệu tóm tắt (Description), số sao đánh giá (Rating), tổng số lượt đánh giá, tầm giá, số điện thoại, địa chỉ đầy đủ, mã vị trí (Plus Code), trang web chính thức, link thực đơn (Menu), link đặt bàn / đặt món (Booking / Order), giờ mở cửa theo từng ngày trong tuần, tọa độ địa lý (Latitude, Longitude), URL Google Maps.
- **Tiện nghi & Dịch vụ (About / Giới thiệu)**: Trích xuất toàn diện mọi thuộc tính được phân nhóm: Phù hợp cho người khuyết tật (lối vào cho xe lăn, chỗ ngồi, nhà vệ sinh...), Lựa chọn dịch vụ (ăn tại chỗ, giao hàng gián tiếp, mua hàng trên xe, mang về...), Tiện nghi (Wi-Fi, quầy bar...), Thanh toán (NFC, thẻ tín dụng...), Bầu không khí, Khách hàng, Bãi đỗ xe, Trẻ em, v.v.
- **Đánh giá (Reviews)**: Tên tác giả, sao đánh giá, thời gian đăng, nội dung nhận xét chi tiết, và link các hình ảnh đính kèm trong bài đánh giá.

---

## 📂 Cấu trúc thư mục

```text
googlemap-places/
├── .venv/                   # Môi trường ảo Python (Playwright, Rich, Croniter, PyYAML)
├── browser_profile/         # Profile trình duyệt Chromium lưu cookie & phiên
├── data/                    # Thư mục lưu file JSON kết quả & SQLite database
│   ├── scheduler.db         # Database SQLite lưu lịch sử, trạng thái cronjob
│   ├── cron.pid             # PID của tiến trình daemon đang chạy
│   └── <job_name>/          # Thư mục kết quả cào theo từng job
├── logs/                    # File log debug của scheduler và từng job
│   ├── daemon.log           # Log của tiến trình background daemon
│   └── <job_name>.log       # Log chi tiết thực thi của từng job
├── src/
│   ├── __init__.py
│   ├── models.py            # Khai báo dữ liệu Place, Review, Coordinates
│   ├── scraper.py           # Engine điều khiển Playwright cào Google Maps
│   ├── scheduler.py         # Engine quản lý lịch trình, hot-reload & sequential queue
│   ├── scheduler_db.py      # SQLite manager cho trạng thái & lịch sử cronjob
│   └── ui.py                # Bảng tóm tắt, banner và preview JSON với Rich
├── jobs.yaml                # File cấu hình danh sách keywords, lịch chạy, limit
├── cron.py                  # CLI điều khiển cronjob (status, errors, logs, run, start, stop)
├── main.py                  # Entrypoint cào thủ công theo dòng lệnh
├── requirements.txt         # Thư viện phụ thuộc
└── README.md                # Tài liệu hướng dẫn sử dụng
```

---

## 🛠️ Hướng dẫn Setup Môi trường (Environment Setup)

### 1. Yêu cầu hệ thống (Prerequisites)
- **Hệ điều hành**: Linux (Ubuntu, Debian, Fedora, CentOS, RHEL...), macOS, hoặc Windows.
- **Python**: Phiên bản 3.10 trở lên (khuyến nghị Python 3.11 - 3.14).
- **Quyền hạn**: Quyền chạy terminal thông thường (chỉ cần `sudo` nếu muốn cài thư viện hệ thống đồ hoạ Linux hoặc đăng ký systemd service).

---

### 2. Các bước cài đặt từ đầu (Step-by-step)

#### Bước 1: Clone mã nguồn hoặc di chuyển vào thư mục dự án
```bash
cd googlemap-places
```

#### Bước 2: Khởi tạo môi trường ảo Python (`.venv`)
Khởi tạo môi trường ảo tách biệt để tránh xung đột thư viện:
```bash
python3 -m venv .venv
```

#### Bước 3: Kích hoạt môi trường ảo (Activate)
- **Trên Linux / macOS**:
  ```bash
  source .venv/bin/activate
  ```
- **Trên Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Trên Windows (Command Prompt - CMD)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```

> 💡 **Mẹo:** File CLI `./cron.py` và `./sync_itravels.py` đã được thiết kế cơ chế tự động tìm và chuyển sang `.venv/bin/python3` nên bạn có thể gõ trực tiếp `./cron.py ...` mà không bắt buộc phải gõ `source .venv/bin/activate` mỗi lần.

#### Bước 4: Cài đặt các thư viện Python
Cập nhật `pip` và cài đặt các thư viện từ `requirements.txt`:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Danh sách thư viện cốt lõi:
- `playwright`: Tự động hoá trình duyệt Chromium để cào Google Maps.
- `rich`: Giao diện CLI chuyên nghiệp (bảng dữ liệu, màu sắc, thanh tiến trình, dashboard).
- `pyyaml`: Đọc & ghi file cấu hình `jobs.yaml`.
- `croniter`: Xử lý lịch chạy định kỳ theo cú pháp cron tiêu chuẩn.
- `python-slugify`: Chuẩn hoá tên file và keyword tiếng Việt.
- `requests`: Gửi dữ liệu đồng bộ REST API đến iTravels.

#### Bước 5: Cài đặt trình duyệt Playwright (Chromium)
Tải trình duyệt Chromium headless được tối ưu cho Playwright:
```bash
playwright install chromium
```

> ⚠️ **Lưu ý quan trọng cho Linux Server / VPS (không có Desktop GUI):**  
> Nếu bạn chạy trên VPS/Server Ubuntu/Debian, cần cài đặt thêm các thư viện đồ họa hệ thống (OS dependencies) cho Chromium:
> ```bash
> # Với Ubuntu / Debian:
> sudo playwright install-deps chromium
> 
> # Hoặc cài thủ công các gói cơ bản nếu không dùng lệnh trên:
> sudo apt-get update && sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
> ```

---

### 3. Cấu hình Tham số & Biến Môi Trường (Config & Env)

Dự án hỗ trợ 2 hình thức cấu hình linh hoạt:

#### Cách 1: Cấu hình trực tiếp trong `jobs.yaml` (Khuyến nghị)
Hệ thống tự động nạp lại (Hot-reload) mỗi khi bạn lưu file `jobs.yaml`:
```yaml
settings:
  cleanup_old_files: true   # Tự động xoá file JSON cũ sau khi cào và sync thành công
  itravels_api:
    api_key: "PcCnUPgiOnZ0wumxG-ZyX2aBLpdlMGC6OecAyfXPEVM"
    base_url: "https://api.itravels.vn"
    site: "khanh-hoa"       # Mã tỉnh thành gửi vào API
    apply: 1                # 1: Ghi thực tế vào DB; 0: Chế độ kiểm tra (dry-run)
    batch_size: 200         # Số lượng bản ghi gửi trong 1 request POST
    max_retries: 3          # Tự động thử lại khi gặp 409 hoặc ngắt mạng
```

#### Cách 2: Sử dụng Biến môi trường (Environment Variables)
Nếu muốn bảo mật key hoặc deploy trên Docker / CI-CD, bạn có thể copy file mẫu [`.env.example`](file:///home/tientp/Workspace/work/dailyve/googlemap-places/.env.example):
```bash
cp .env.example .env
```
Nội dung hỗ trợ:
```bash
export ITRAVELS_API_KEY="PcCnUPgiOnZ0wumxG-ZyX2aBLpdlMGC6OecAyfXPEVM"
export ITRAVELS_SITE="khanh-hoa"
export ITRAVELS_BASE_URL="https://api.itravels.vn"
```

---

### 4. Kiểm tra & Chạy thử nghiệm môi trường (Verification)

#### Kiểm tra file cấu hình và kết nối:
```bash
./cron.py validate
```

#### Chạy thử nghiệm 1 tác vụ nhỏ (Smoke Test):
```bash
# Cào thử 3 địa điểm của ẩm thực để kiểm tra trình duyệt Playwright
./cron.py run am_thuc_khanh_hoa -l 3

# Kiểm tra đồng bộ API ở chế độ an toàn (không ghi dữ liệu)
./sync_itravels.py --dry-run
```

#### Kiểm tra bảng trạng thái tổng quát:
```bash
./cron.py status
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
    "price_range": "394.911 ₫",
    "pricing": {
      "main_price": "394.911 ₫",
      "price_range": null,
      "partners": [
        {
          "partner": "HomeToGo",
          "price": "394.911 ₫",
          "link": "https://www.google.com/travel/lodging/clk?...",
          "note": "Hủy đặt phòng miễn phí đến hết ngày 6 thg 10"
        },
        {
          "partner": "Agoda",
          "price": "397.568 ₫",
          "link": "https://www.google.com/travel/lodging/clk?...",
          "note": null
        }
      ]
    },
    "address": "Số 6, Trần Cao Vân/Công trường Quốc Tế/42 Hồ Con Rùa, Quận 3, Hồ Chí Minh, Việt Nam",
    "phone": "+84 1900 3013",
    "website": "https://phela.vn/",
    "menu": {
      "link": "https://phela.vn/menu",
      "dishes": [
        {
          "name": "Ô Long Sữa Phê La",
          "price": "55.000 ₫",
          "description": "Trà ô long đặc sản kết hợp sữa tươi béo ngậy",
          "photo": "https://lh3.googleusercontent.com/...=s1600"
        }
      ],
      "photos": [
        "https://lh3.googleusercontent.com/...=s1600"
      ]
    },
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

---

## ⏰ Cào Dữ Liệu Định Kỳ & Tác Vụ Cronjob

Hệ thống tích hợp sẵn một **Scheduler Daemon & CLI Manager** hoàn chỉnh (`cron.py`), cho phép thiết lập và quản lý các tác vụ cào lặp lại định kỳ một cách thuận tiện, dễ debug và an toàn tuyệt đối.

### 🌟 Điểm nổi bật
- **Cấu hình trực quan qua `jobs.yaml`**: Dễ dàng gom nhóm nhiều nhóm từ khóa, điều chỉnh `limit`, `max_reviews`, `concurrency`. Tạm tắt keyword bằng dấu `#` hoặc tạm tắt job bằng `enabled: false`.
- **Lịch chạy linh hoạt**: Hỗ trợ cả định dạng thời gian tự nhiên (`every: 6h`, `every: 30m`, `every: 1d`) lẫn cú pháp cron tiêu chuẩn (`cron: "0 2 * * *"`).
- **Hot-Reload thông minh**: Tự động nhận diện thay đổi trong `jobs.yaml` và cập nhật lịch trình ngay lập tức mà không cần khởi động lại tiến trình.
- **Thực thi tuần tự & Khả năng chịu lỗi (Fault-Tolerant)**: Các job chạy lần lượt để tránh quá tải RAM và không bị Google chặn IP. Nếu 1 keyword gặp lỗi mạng/captcha, hệ thống vẫn ghi nhận lỗi, bảo toàn kết quả các keyword trước đó và tiếp tục cào keyword kế tiếp.
- **Bộ lệnh Debug toàn diện**: Bảng trạng thái trực quan, theo dõi lỗi tập trung và xem log chi tiết từng job ngay trên terminal.

---

### 1. Cấu hình Tác vụ (`jobs.yaml`)

Chỉnh sửa trực tiếp file `jobs.yaml` tại thư mục gốc:

```yaml
jobs:
  # Nhóm 1: Quán cà phê Quận 1 (Cứ 6 tiếng cào 1 lần)
  cafe_quan1:
    enabled: true
    description: "Cào danh sách quán cà phê nổi bật tại Quận 1"
    schedule:
      every: "6h"            # hoặc: cron: "0 */6 * * *"
    limit: 10                # Giới hạn số địa điểm cào mỗi keyword
    max_reviews: 50          # Giới hạn review (hoặc 'all')
    concurrency: 3           # Số tab cào song song
    sort: "most_relevant"    # most_relevant, newest, highest_rating, lowest_rating
    keywords:
      - "cà phê nguyễn huệ quận 1"
      - "specialty coffee ben nghe quan 1"
      # - "the coffee house nguyen thi minh khai" # Thêm dấu # để tạm ngưng

  # Nhóm 2: Nhà hàng Hà Nội (Chạy 02:00 sáng mỗi ngày)
  nha_hang_hanoi:
    enabled: false           # Đổi thành true để bật
    description: "Cào thông tin ẩm thực Hà Nội"
    schedule:
      cron: "0 2 * * *"
    limit: 20
    max_reviews: 100
    concurrency: 4
    keywords:
      - "phở bò ngon hoàn kiếm hà nội"
      - "bún chả hương liên hà nội"
```

---

### 2. Các Lệnh Điều Khiển CLI (`cron.py`)

#### 📊 Xem Bảng Trạng thái Realtime (`status`)
Hiển thị danh sách tất cả các job, trạng thái hiện tại (Đang chạy 🟢, Thành công ✅, Lỗi 🔴, Chờ chạy ⏳), lần chạy cuối, thời lượng và lịch chạy kế tiếp:

```bash
./.venv/bin/python cron.py status
# hoặc chạy file trực tiếp
./cron.py status
```

#### 🚨 Xem Danh sách Lần Chạy Bị Lỗi (`errors`)
Liệt kê nhanh các lần chạy thất bại gần nhất, tóm tắt thông điệp lỗi và đường dẫn file log debug:

```bash
./cron.py errors
```

#### 📜 Xem Chi Tiết Log Debug (`logs`)
Đọc ngay các dòng log cuối cùng của một job cụ thể (hoặc log của daemon) để chẩn đoán nguyên nhân lỗi:

```bash
# Xem 50 dòng log cuối của job 'cafe_quan1'
./cron.py logs cafe_quan1

# Xem 100 dòng log cuối
./cron.py logs cafe_quan1 -n 100

# Xem log tiến trình chạy ngầm của daemon
./cron.py logs daemon
```

#### ⚡ Cào Dữ Liệu Ngay Lập Tức (`run` hoặc `crawl`)
Cho phép cào ngay lập tức mà không cần chờ đến giờ hẹn trong lịch:

```bash
# Cào ngay lập tức lần lượt TẤT CẢ các task đang bật (mặc định)
./cron.py run
# hoặc
./cron.py run all
./cron.py run --all

# Cào ngay lập tức 1 task cụ thể
./cron.py run khach_san_khanh_hoa

# Cào ngay lần lượt một nhóm task được chỉ định
./cron.py run khach_san_khanh_hoa homestay_khanh_hoa

# Test nhanh với số lượng địa điểm giới hạn (ví dụ: cào thử 2 địa điểm/keyword)
./cron.py run am_thuc_khanh_hoa -l 2

# Mở cửa sổ trình duyệt (headed mode) để theo dõi trực tiếp
./cron.py run homestay_khanh_hoa --headed
```

#### ✅ Kiểm Tra Cú Pháp File Cấu Hình (`validate`)
Kiểm tra xem file `jobs.yaml` có đúng định dạng, các biểu thức cron hay số limit có hợp lệ hay không:

```bash
./cron.py validate
```

#### 🚀 Khởi Chạy Scheduler Daemon (`start`)
Khi khởi chạy scheduler, hệ thống **mặc định sẽ cào ngay lập tức lần lượt tất cả các task đợt đầu tiên**, sau đó tự động lên lịch chạy định kỳ theo thời gian trong `jobs.yaml`:

- **Chạy trực tiếp trên Terminal (Foreground)** — Xem live log cào ngay đợt đầu, nhấn `Ctrl + C` để dừng an toàn:
  ```bash
  ./cron.py start
  ```

- **Chạy ngầm (Background Daemon)** — Tự động fork tiến trình ngầm, cào ngay đợt đầu và ghi nhận vào log:
  ```bash
  ./cron.py start -d
  ```

- **Tùy chọn chỉ chờ đúng giờ hẹn (không cào ngay đợt đầu)**:
  ```bash
  ./cron.py start --wait-schedule
  # hoặc dạng daemon
  ./cron.py start -d --wait-schedule
  ```

#### 🛑 Dừng Daemon Đang Chạy Ngầm (`stop`)
Dừng an toàn tiến trình daemon và đóng trình duyệt sạch sẽ:

```bash
./cron.py stop
```

---

### 3. Cài Đặt Tự Chạy Cùng Hệ Thống Linux (Systemd Service)

Để scheduler tự động khởi chạy mỗi khi mở máy hoặc khởi động lại VPS/Server:

```bash
# 1. Tạo file service cấu hình sẵn theo đường dẫn hiện tại
./cron.py install-service

# 2. Cài đặt vào systemd
sudo cp googlemaps-cron.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now googlemaps-cron

# 3. Kiểm tra trạng thái service
sudo systemctl status googlemaps-cron
```

---

### 4. Cấu Trúc File Đầu Ra Khi Cào Định Kỳ

Mỗi job khi cào định kỳ sẽ lưu trữ kết quả độc lập theo thư mục riêng trong `data/`:
```text
data/
├── scheduler.db          # Database SQLite theo dõi lịch sử và trạng thái
└── <job_name>/
    ├── <keyword_slug>_20261014_080000.json
    └── <keyword_slug>_20261014_140000.json
```
Lịch sử từng lần cào được lưu riêng biệt theo mốc thời gian, không bị ghi đè, giúp dễ dàng đối chiếu và phân tích biến động dữ liệu theo thời gian.

---

## 📡 Tự Động Bắn Dữ Liệu Lên Hệ Thống iTravels API

Hệ thống tích hợp module đồng bộ trực tiếp (`src/itravels_sync.py` & `sync_itravels.py`) với hệ thống **iTravels**.

### 🌟 Tính năng đồng bộ
- **Tự động bắn API ngay sau khi cào thành công**: Khi một job cào xong, hệ thống tự động kiểm tra cấu hình `itravels_type` (`dia-danh`, `am-thuc`, `khach-san`, `homestay`) và gửi dữ liệu ngay lập tức.
- **Tự động chia lô (Batching)**: Chia nhỏ dữ liệu thành từng lô an toàn (mặc định 200 bản ghi/lô, đảm bảo luôn <20MB và <2000 bản ghi theo quy định API).
- **Cơ chế Chống nghẽn & Retry thông minh (HTTP 409)**: Khi gặp lỗi 409 (*đang có lượt import khác đang chạy trên server*), client tự động chờ 15s - 30s và thử lại tối đa 4 lần.
- **Bảo toàn dữ liệu theo `place_id`**: Hệ thống iTravels tự động cập nhật nếu địa điểm đã có hoặc tạo mới nếu là địa điểm mới. Với khách sạn/homestay, tự động đính kèm tham số `ngayCao=YYYY-MM-DD`.

### 1. Cấu hình trong `jobs.yaml`
```yaml
settings:
  itravels_api:
    api_key: "PcCnUPgiOnZ0wumxG-ZyX2aBLpdlMGC6OecAyfXPEVM"
    base_url: "https://api.itravels.vn"
    site: "khanh-hoa"       # Mã tỉnh thành
    apply: 1                # 1: Ghi thực tế; 0: Chỉ kiểm tra báo cáo thử nghiệm
    batch_size: 200         # Số bản ghi mỗi request
    max_retries: 4

jobs:
  am_thuc_khanh_hoa:
    enabled: true
    itravels_type: "am-thuc" # dia-danh | am-thuc | khach-san | homestay
    auto_sync: true          # Tự động gửi API sau khi cào
    ...
```

### 2. Các Lệnh Đồng Bộ Thủ Công
```bash
# Kiểm tra thử nghiệm (Dry-run, apply=0: chỉ kiểm tra, không lưu vào DB server)
./cron.py sync --dry-run
# hoặc cho file cụ thể
./sync_itravels.py data/am_thuc_khanh_hoa/...json --dry-run

# Đồng bộ thực tế (apply=1) cho tất cả các job có cấu hình
./cron.py sync

# Đồng bộ cho 1 job cụ thể
./cron.py sync am_thuc_khanh_hoa

# Dùng công cụ độc lập sync_itravels.py cho file JSON bất kỳ
./sync_itravels.py data/am_thuc_khanh_hoa/...json --type am-thuc
```

---

## 🧹 Tự Động Dọn Dẹp Dữ Liệu Cũ (Auto-Cleanup)

Để tránh ổ đĩa bị đầy hoặc tích tụ các file JSON cũ qua nhiều tuần chạy định kỳ:
- **Tự động kích hoạt**: Mỗi khi một job cào thành công (và sau khi đã bắn API xong), hệ thống tự động quét thư mục `data/<job_name>/` và **xoá toàn bộ các file JSON cũ của những lần chạy trước**, chỉ giữ lại file kết quả mới nhất vừa cào.
- **Có thể tắt tính năng này**: Bằng cách đổi `cleanup_old_files: false` trong `jobs.yaml` nếu bạn muốn lưu lại toàn bộ snapshot lịch sử.

### Lệnh Dọn Dẹp Thủ Công (`cleanup` hoặc `clean`):
```bash
# Quét và dọn dẹp tất cả các file cũ của toàn bộ các job
./cron.py cleanup
# hoặc viết tắt
./cron.py clean

# Chỉ dọn dẹp cho một job cụ thể
./cron.py cleanup --job am_thuc_khanh_hoa
```

