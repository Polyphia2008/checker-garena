#!/usr/bin/env python3
"""Garena Account Checker - Flask Application"""
import os
import re
import json
import hashlib
import secrets
import threading
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, jsonify, redirect,
    url_for, session, flash, g
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///garena_checker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
CORS(app, supports_credentials=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'
login_manager.login_message = 'Vui lòng đăng nhập để tiếp tục.'
login_manager.login_message_category = 'warning'

# ──────────────────────────────────────────────
# Database Models
# ──────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    daily_limit = db.Column(db.Integer, default=100)
    checks_today = db.Column(db.Integer, default=0)
    last_check_date = db.Column(db.Date, default=date.today)
    total_checks = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    api_key = db.Column(db.String(64), unique=True, nullable=True)

    checks = db.relationship('CheckHistory', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def can_check(self):
        today = date.today()
        if self.last_check_date != today:
            self.checks_today = 0
            self.last_check_date = today
            db.session.commit()
        return self.checks_today < self.daily_limit

    def remaining_checks(self):
        today = date.today()
        if self.last_check_date != today:
            return self.daily_limit
        return max(0, self.daily_limit - self.checks_today)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'is_active': self.is_active,
            'daily_limit': self.daily_limit,
            'checks_today': self.checks_today,
            'remaining': self.remaining_checks(),
            'total_checks': self.total_checks,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
        }


class CheckHistory(db.Model):
    __tablename__ = 'check_history'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uid = db.Column(db.String(50), nullable=False)
    result_data = db.Column(db.Text, nullable=True)  # JSON string
    status = db.Column(db.String(20), default='success')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'uid': self.uid,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'result_data': self.result_data,
        }


class SiteSettings(db.Model):
    __tablename__ = 'site_settings'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        s = db.session.get(SiteSettings, key) or SiteSettings.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = db.session.get(SiteSettings, key) or SiteSettings.query.filter_by(key=key).first()
        if s:
            s.value = value
        else:
            s = SiteSettings(key=key, value=value)
            db.session.add(s)
        db.session.commit()


# ──────────────────────────────────────────────
# Flask-Login user loader
# ──────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ──────────────────────────────────────────────
# Context processor
# ──────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return {
        'now': datetime.utcnow(),
        'site_name': SiteSettings.get('site_name', 'Garena Account Checker'),
        'app_version': '2.0.0',
    }


# ──────────────────────────────────────────────
# Auth Decorators
# ──────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login_page'))
        if not current_user.is_admin:
            flash('Bạn không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'Vui lòng đăng nhập.'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ──────────────────────────────────────────────
# Routes - Pages
# ──────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/register')
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/history')
@login_required
def history_page():
    return render_template('history.html')


@app.route('/admin')
@admin_required
def admin_panel():
    return render_template('admin.html')


@app.route('/admin/users')
@admin_required
def admin_users():
    return render_template('admin_users.html')


# ──────────────────────────────────────────────
# API Routes - Auth
# ──────────────────────────────────────────────
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dữ liệu không hợp lệ.'}), 400

    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'success': False, 'error': 'Vui lòng điền đầy đủ thông tin.'}), 400

    if len(username) < 3:
        return jsonify({'success': False, 'error': 'Tên đăng nhập ít nhất 3 ký tự.'}), 400

    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Mật khẩu ít nhất 6 ký tự.'}), 400

    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({'success': False, 'error': 'Email không hợp lệ.'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Tên đăng nhập đã tồn tại.'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email đã được sử dụng.'}), 400

    user = User(
        username=username,
        email=email,
        api_key=secrets.token_hex(32),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return jsonify({'success': True, 'message': 'Đăng ký thành công!', 'user': user.to_dict()})


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dữ liệu không hợp lệ.'}), 400

    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Vui lòng điền đầy đủ thông tin.'}), 400

    user = User.query.filter_by(username=username).first()
    if not user:
        user = User.query.filter_by(email=username.lower()).first()

    if not user or not user.check_password(password):
        return jsonify({'success': False, 'error': 'Tên đăng nhập hoặc mật khẩu không đúng.'}), 401

    if not user.is_active:
        return jsonify({'success': False, 'error': 'Tài khoản đã bị khóa. Liên hệ admin.'}), 403

    login_user(user, remember=data.get('remember', False))
    return jsonify({'success': True, 'message': 'Đăng nhập thành công!', 'user': user.to_dict()})


@app.route('/api/auth/logout', methods=['POST'])
@login_required
def api_logout():
    logout_user()
    return jsonify({'success': True, 'message': 'Đã đăng xuất.'})


@app.route('/api/auth/me')
@login_required
def api_me():
    return jsonify({'success': True, 'user': current_user.to_dict()})


# ──────────────────────────────────────────────
# API Routes - Checker
# ──────────────────────────────────────────────
@app.route('/api/check', methods=['POST'])
@api_login_required
def api_check():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dữ liệu không hợp lệ.'}), 400

    uid = str(data.get('uid', '')).strip()
    if not uid:
        return jsonify({'success': False, 'error': 'Vui lòng nhập UID Garena.'}), 400

    if not uid.isdigit():
        return jsonify({'success': False, 'error': 'UID không hợp lệ (chỉ chứa số).'}), 400

    if not current_user.can_check():
        return jsonify({
            'success': False,
            'error': f'Bạn đã dùng hết {current_user.daily_limit} lượt check hôm nay. Vui lòng quay lại vào ngày mai.',
            'remaining': 0,
        }), 429

    # Check cache (same UID checked in last 30 mins)
    recent = CheckHistory.query.filter_by(
        user_id=current_user.id, uid=uid
    ).order_by(CheckHistory.created_at.desc()).first()

    if recent and (datetime.utcnow() - recent.created_at).seconds < 1800:
        result_data = json.loads(recent.result_data) if recent.result_data else {}
        return jsonify({
            'success': True,
            'data': result_data,
            'remaining': current_user.remaining_checks(),
            'cached': True,
        })

    # Run checker
    try:
        result = run_garena_checker(uid)
    except Exception as e:
        print(f"Checker error: {e}")
        return jsonify({'success': False, 'error': f'Lỗi hệ thống: {str(e)}'}), 500

    # Update user stats
    current_user.checks_today += 1
    current_user.total_checks += 1
    current_user.last_check_date = date.today()

    # Save history
    history = CheckHistory(
        user_id=current_user.id,
        uid=uid,
        result_data=json.dumps(result, ensure_ascii=False),
        status='success',
    )
    db.session.add(history)
    db.session.commit()

    return jsonify({
        'success': True,
        'data': result,
        'remaining': current_user.remaining_checks(),
        'cached': False,
    })


@app.route('/api/history')
@api_login_required
def api_history():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = CheckHistory.query.filter_by(user_id=current_user.id)\
        .order_by(CheckHistory.created_at.desc())

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'success': True,
        'data': [item.to_dict() for item in items],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page),
    })


@app.route('/api/stats')
@api_login_required
def api_stats():
    today = date.today()
    total_checks = current_user.total_checks
    today_checks = current_user.checks_today
    if current_user.last_check_date != today:
        today_checks = 0

    return jsonify({
        'success': True,
        'data': {
            'total_checks': total_checks,
            'today_checks': today_checks,
            'daily_limit': current_user.daily_limit,
            'remaining': max(0, current_user.daily_limit - today_checks),
            'username': current_user.username,
            'is_admin': current_user.is_admin,
        }
    })


# ──────────────────────────────────────────────
# API Routes - Admin
# ──────────────────────────────────────────────
@app.route('/api/admin/stats')
@admin_required
def api_admin_stats():
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_checks = CheckHistory.query.count()
    today_checks = CheckHistory.query.filter(
        CheckHistory.created_at >= date.today()
    ).count()

    return jsonify({
        'success': True,
        'data': {
            'total_users': total_users,
            'active_users': active_users,
            'total_checks': total_checks,
            'today_checks': today_checks,
        }
    })


@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()

    query = User.query
    if search:
        query = query.filter(
            (User.username.contains(search)) |
            (User.email.contains(search))
        )

    total = query.count()
    users = query.order_by(User.created_at.desc())\
        .offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'success': True,
        'data': [u.to_dict() for u in users],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page),
    })


@app.route('/api/admin/user/<int:user_id>', methods=['PUT'])
@admin_required
def api_admin_update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Không tìm thấy user.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dữ liệu không hợp lệ.'}), 400

    if 'is_active' in data:
        user.is_active = bool(data['is_active'])
    if 'is_admin' in data and user.id != current_user.id:
        user.is_admin = bool(data['is_admin'])
    if 'daily_limit' in data:
        user.daily_limit = max(1, int(data['daily_limit']))
    if 'checks_today' in data:
        user.checks_today = max(0, int(data['checks_today']))

    db.session.commit()
    return jsonify({'success': True, 'message': 'Cập nhật thành công.', 'user': user.to_dict()})


@app.route('/api/admin/user/<int:user_id>/checks')
@admin_required
def api_admin_user_checks(user_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = CheckHistory.query.filter_by(user_id=user_id)\
        .order_by(CheckHistory.created_at.desc())

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'success': True,
        'data': [item.to_dict() for item in items],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page),
    })


# ──────────────────────────────────────────────
# Garena Checker Engine
# ──────────────────────────────────────────────
def run_garena_checker(uid):
    """
    Use Playwright to scrape Garena account info.
    Returns dict with all account details.
    """
    from playwright.sync_api import sync_playwright

    result = {
        'uid': uid,
        'name_garena': '',
        'name_game': '',
        'level': 0,
        'rank_current': '',
        'stars_current': '',
        'qh': 0,
        'so': 0,
        'email': '',
        'email_verified': False,
        'phone': '',
        'pass_set': '',
        'authen': '',
        'fb': '',
        'cccd': '',
        'heroes': 0,
        'skins': 0,
        'rank_highest': '',
        'stars_highest': '',
        'total_matches': 0,
        'total_wins': 0,
        'total_mvp': 0,
        'win_rate': 0,
        'sss_skins': [],
        'ss_skins': [],
        'anime_skins': [],
        'ssm_count': 0,
        'sp_count': 0,
        's_count': 0,
        'a_count': 0,
        'top_heroes': [],
        'ban_status': '',
        'status': '',
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1366, 'height': 768},
                locale='vi-VN',
            )
            page = context.new_page()

            # Go to Garena check page
            url = f'https://check.quanlyquangcao.com.vn/api/garena/v3?uid={uid}'
            response = page.goto(url, timeout=30000, wait_until='networkidle')

            body_text = page.content()

            if 'error' in body_text.lower() or 'not found' in body_text.lower():
                result['status'] = 'Không tìm thấy thông tin'
                browser.close()
                return result

            # Try to get JSON response
            page_text = page.inner_text('body')
            try:
                # Try parsing as JSON
                data = json.loads(page_text)
                if isinstance(data, dict):
                    result.update(parse_garena_api_response(data))
            except (json.JSONDecodeError, Exception):
                # Try another API endpoint
                alt_url = f'https://api.quanlyquangcao.com.vn/garena/check?uid={uid}'
                try:
                    page2 = context.new_page()
                    page2.goto(alt_url, timeout=20000, wait_until='networkidle')
                    alt_text = page2.inner_text('body')
                    data = json.loads(alt_text)
                    if isinstance(data, dict):
                        result.update(parse_garena_api_response(data))
                    page2.close()
                except Exception:
                    pass

            browser.close()
    except Exception as e:
        print(f"Playwright error: {e}")
        result['status'] = f'Lỗi: {str(e)[:100]}'

    return result


def parse_garena_api_response(data):
    """Parse API response into standardized format."""
    result = {}

    # Map common field names
    field_mapping = {
        'uid': 'uid',
        'name': 'name_garena',
        'name_garena': 'name_garena',
        'name_game': 'name_game',
        'level': 'level',
        'rank': 'rank_current',
        'rank_current': 'rank_current',
        'stars': 'stars_current',
        'stars_current': 'stars_current',
        'qh': 'qh',
        'so': 'so',
        'email': 'email',
        'email_verified': 'email_verified',
        'phone': 'phone',
        'sdt': 'phone',
        'password': 'pass_set',
        'pass': 'pass_set',
        'authen': 'authen',
        '2fa': 'authen',
        'facebook': 'fb',
        'fb': 'fb',
        'cccd': 'cccd',
        'hero_count': 'heroes',
        'heroes': 'heroes',
        'skin_count': 'skins',
        'skins': 'skins',
        'rank_highest': 'rank_highest',
        'total_matches': 'total_matches',
        'total_matches_season': 'total_matches',
        'total_wins': 'total_wins',
        'total_wins_season': 'total_wins',
        'total_mvp': 'total_mvp',
        'total_mvp_season': 'total_mvp',
        'win_rate': 'win_rate',
        'win_rate_season': 'win_rate',
        'ban_status': 'ban_status',
        'ban': 'ban_status',
        'status': 'status',
    }

    for src_key, dst_key in field_mapping.items():
        if src_key in data and data[src_key] is not None:
            result[dst_key] = data[src_key]

    # Parse skin categories
    for skin_cat in ['sss_skins', 'ss_skins', 'anime_skins', 'ssm_skins']:
        if skin_cat in data:
            result[skin_cat.replace('_skins', '_skins')] = data[skin_cat]

    # Parse skin counts
    for cat in ['ssm_count', 'sp_count', 's_count', 'a_count']:
        if cat in data:
            result[cat] = int(data[cat]) if data[cat] else 0

    # Top heroes
    if 'top_heroes' in data:
        result['top_heroes'] = data['top_heroes']

    # Parse nested data
    if 'data' in data and isinstance(data['data'], dict):
        result.update(parse_garena_api_response(data['data']))

    # Clean up null values
    for key in list(result.keys()):
        if result[key] is None:
            if key in ['heroes', 'skins', 'level', 'qh', 'so', 'total_matches', 'total_wins', 'total_mvp', 'ssm_count', 'sp_count', 's_count', 'a_count']:
                result[key] = 0
            elif key in ['win_rate']:
                result[key] = 0.0
            else:
                result[key] = ''

    return result


# ──────────────────────────────────────────────
# Error handlers
# ──────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Không tìm thấy.'}), 404
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Lỗi máy chủ.'}), 500
    return render_template('500.html'), 500


# ──────────────────────────────────────────────
# Create tables and default admin
# ──────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()

        # Create default admin if none exists
        if not User.query.filter_by(is_admin=True).first():
            admin = User(
                username='admin',
                email='admin@garena-checker.local',
                is_admin=True,
                daily_limit=9999,
                api_key=secrets.token_hex(32),
            )
            admin.set_password('admin123')
            db.session.add(admin)

            # Create demo user
            demo = User(
                username='demo',
                email='demo@example.com',
                daily_limit=100,
                api_key=secrets.token_hex(32),
            )
            demo.set_password('demo123')
            db.session.add(demo)
            db.session.commit()
            print("Default admin created: admin / admin123")
            print("Demo user created: demo / demo123")

        # Set site name
        if not SiteSettings.get('site_name'):
            SiteSettings.set('site_name', 'Garena Account Checker - Kiểm Tra Acc Liên Quân')


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=3000, debug=True)
