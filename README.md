# Garena Account Checker

## Tổng quan
- **Tên dự án**: Garena Account Checker
- **Mục đích**: Kiểm tra thông tin tài khoản Garena Liên Quân Mobile
- **GitHub**: https://github.com/Polyphia2008/checker-garena

## Tính năng đã hoàn thành

### Frontend
- Trang chủ với form check UID
- Đăng ký / Đăng nhập tài khoản
- Dashboard thống kê (lượt check hôm nay, còn lại, tổng, limit)
- Lịch sử check với phân trang và modal chi tiết
- Admin Panel: thống kê hệ thống, quản lý users (sửa limit, khóa/mở khóa, phân quyền admin)
- Responsive design với mobile sidebar
- Theme Metronic-style với Inter font, glassmorphism

### Backend
- Flask + SQLAlchemy + SQLite
- Xác thực: Flask-Login, bcrypt hash password
- Phân quyền: user thường vs admin
- Logic lượt check: mỗi user 100 lượt/ngày, reset hàng ngày
- Caching: UID đã check trong 30 phút không gọi lại API
- API Garena Checker: Playwright + Chromium headless
- Admin API: quản lý users, thống kê hệ thống

### API Endpoints
| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | /api/auth/register | - | Đăng ký |
| POST | /api/auth/login | - | Đăng nhập |
| POST | /api/auth/logout | Login | Đăng xuất |
| GET | /api/auth/me | Login | Thông tin user hiện tại |
| POST | /api/check | Login | Check UID Garena |
| GET | /api/history | Login | Lịch sử check (phân trang) |
| GET | /api/stats | Login | Thống kê cá nhân |
| GET | /api/admin/stats | Admin | Thống kê hệ thống |
| GET | /api/admin/users | Admin | Danh sách users (phân trang) |
| PUT | /api/admin/user/{id} | Admin | Cập nhật thông tin user |

## Tài khoản mặc định
- **Admin**: admin / admin123
- **Demo**: demo / demo123

## Cài đặt và Chạy

```bash
# Cài dependencies
pip install flask flask-login flask-cors flask-sqlalchemy requests cryptography pillow opencv-python numpy ddddocr playwright bcrypt

# Cài Chromium cho Playwright
python3 -m playwright install chromium

# Chạy server
python3 app.py
# Server chạy tại http://0.0.0.0:3000
```

## Công nghệ sử dụng
- **Backend**: Python 3, Flask, SQLAlchemy, SQLite
- **Frontend**: Jinja2 Templates, Font Awesome 6, Inter Font
- **Automation**: Playwright + Chromium (headless)
- **Auth**: Flask-Login, bcrypt

## Cấu trúc dự án
```
webapp/
├── app.py                 # Flask application chính
├── ecosystem.config.cjs   # PM2 config
├── templates/
│   ├── base.html          # Layout chung
│   ├── index.html         # Trang chủ - Check UID
│   ├── login.html         # Đăng nhập
│   ├── register.html      # Đăng ký
│   ├── dashboard.html     # Dashboard user
│   ├── history.html       # Lịch sử check
│   ├── admin.html         # Admin Panel
│   ├── admin_users.html   # Quản lý Users
│   ├── 404.html           # Error pages
│   └── 500.html
└── static/
    └── assets/
        ├── css/
        │   └── styles.css
        └── vendors/
            └── keenicons/
                └── styles.bundle.css
```

## Dữ liệu đầu ra mẫu
```
UID: 502376961 | NAME GARENA: u502376961 | NAME GAME: nhatminh3001 | LV: 30
RANK HIỆN TẠI: T.Anh V (3s) | QH: 23 | SÒ: 0
EMAIL: Yes [ski****@hotmail.com] (ĐÃ XÁC THỰC)
SĐT: YES [+84 ****7022] | PASS: YES | AUTHEN: Yes (2FA)
FB: YES [896216423849990] | CCCD: NO
TƯỚNG: 108 | SKIN: 307
SSS(2): Lauriel Thứ nguyên vệ thần, Hayate Tu Di Thánh Đế
SS(18): Gildur Tiệc Bãi Biển, ...
Anime(11): Zephys Inosuke Hashibira, ...
RANK CAO NHẤT: Chiến Tướng (10s)
TỔNG SỐ TRẬN: 312 | THẮNG: 163 | MVP: 35 | TỈ LỆ THẮNG: 52.24%
TƯỚNG TỦ: Florentino (52.91% 189 trận), Ngộ Không (72.73% 11 trận), ...
```

## Trạng thái
- ✅ Backend API hoàn chỉnh
- ✅ Frontend với auth đầy đủ
- ✅ Admin Panel với quản lý users
- ✅ Phân quyền user/admin rõ ràng
- ✅ Logic 100 lượt/ngày/user
- ✅ Lịch sử check + caching
- ✅ GitHub push tự động
- 🔄 Checker engine (Playwright scraping - cần URL API thực tế của Garena)
