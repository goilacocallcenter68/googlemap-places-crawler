#!/usr/bin/env bash
# ==============================================================================
# Script tự động cập nhật môi trường và khởi động lại sau khi git pull
# ==============================================================================
set -e

# Chuyển về đúng thư mục chứa script
cd "$(dirname "$0")"

echo "🔄 Đang cập nhật hệ thống Google Maps Crawler..."

# 1. Cấp quyền thực thi cho các CLI script
chmod +x cron.py sync_itravels.py 2>/dev/null || true

# 2. Cập nhật thư viện Python nếu có thay đổi trong requirements.txt
if [ -d ".venv" ]; then
    echo "📦 Đang kiểm tra & cập nhật thư viện Python..."
    ./.venv/bin/pip install -r requirements.txt --quiet
elif command -v pip &> /dev/null; then
    pip install -r requirements.txt --quiet
fi

# 3. Kiểm tra tính hợp lệ của cấu hình
echo "🔍 Kiểm tra tính hợp lệ của cấu hình jobs.yaml..."
./cron.py validate

# 4. Khởi động lại dịch vụ Scheduler
echo "🚀 Khởi động lại Scheduler Daemon..."
if command -v systemctl &> /dev/null && systemctl is-active --quiet googlemaps-cron.service 2>/dev/null; then
    sudo systemctl restart googlemaps-cron.service
    echo "✔ Đã khởi động lại qua Systemd Service (googlemaps-cron.service)."
else
    ./cron.py stop 2>/dev/null || true
    ./cron.py start -d
    echo "✔ Đã khởi động lại Scheduler Daemon ngầm."
fi

echo ""
echo "=================================================================="
echo "🎉 Cập nhật thành công! Kiểm tra trạng thái bên dưới:"
echo "=================================================================="
./cron.py status
