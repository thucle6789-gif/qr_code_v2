import streamlit as st
import requests
import cv2
import numpy as np
from datetime import datetime, date
from zoneinfo import ZoneInfo
import time
import hashlib
import json
from streamlit_qrcode_scanner import qrcode_scanner

# =====================================================
# CẤU HÌNH
# =====================================================
def normalize_role(role_str: str) -> str:
    """Chuẩn hóa role về dạng không dấu, không khoảng trắng để so sánh an toàn.
       'SẢN XUẤT' / 'san xuat' / 'sản xuất' → 'sanxuat'
       'NGƯỜI XEM' / 'nguoi xem' / 'người xem' → 'nguoixem'
    """
    import unicodedata
    s = role_str.strip().lower()
    # Bỏ dấu tiếng Việt
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Bỏ khoảng trắng
    s = s.replace(' ', '')
    return s  # 'sanxuat' hoặc 'nguoixem' hoặc ''

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz5-wxqgsgvEHCM5wgakFaNYz_M3IezI8_PzuiZg_-0Buo77wPI6Upq3k50YOM5cF7XdA/exec"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

DANH_SACH_CONG_DOAN = [
    "P013_Tạo phôi và Sơchế","P014_Tinh chế và Định hình","P015_Chà nhám và Bề mặt",
    "P016_Lắp ráp và Liên kết","P017_Làm nguội và Hoàn thiện","P018_Sơn - Màu",
    "P019_Washing - Cleaning","P20_Lắp ráp hoàn thiện","P021_Đóng gói hoàn thành"
]

# =====================================================
# PAGE CONFIG & CSS
# =====================================================
st.set_page_config(page_title="Hệ Thống Quét QR Xưởng", layout="wide", initial_sidebar_state="collapsed")

# =====================================================
# QUẢN LÝ SESSION QUA st.query_params
# Python đọc query_params đồng bộ ngay lần render đầu tiên
# Token = hashlib của user+ten+secret, lưu trong URL ?t=TOKEN&u=USER&n=TEN&r=ROLE&ts=TS
# =====================================================
SESSION_SECRET = "qr-xuong-2024-secret"

def make_token(user: str, ten: str, ts: int) -> str:
    raw = f"{user}|{ten}|{ts}|{SESSION_SECRET}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def save_session(user: str, ten: str, role: str):
    """Ghi session vào query_params — browser lưu trong URL, reload vẫn còn."""
    ts    = int(time.time())
    token = make_token(user, ten, ts)
    st.query_params.update({
        "t":  token,
        "u":  user,
        "n":  ten,
        "r":  role,
        "ts": str(ts),
    })

def clear_session():
    """Xóa toàn bộ query_params khi đăng xuất."""
    st.query_params.clear()

def read_session():
    """
    Đọc session từ query_params — đồng bộ, không cần JS.
    Trả về dict {user, ten, role} hoặc None nếu không hợp lệ / hết hạn.
    """
    try:
        p     = st.query_params
        token = p.get("t",  "")
        user  = p.get("u",  "")
        ten   = p.get("n",  "")
        role  = p.get("r",  "")
        ts    = int(p.get("ts", "0"))
        if not all([token, user, ten, ts]):
            return None
        # Kiểm tra hạn 30 ngày
        if (time.time() - ts) > 30 * 86400:
            return None
        # Kiểm tra token hợp lệ
        if make_token(user, ten, ts) != token:
            return None
        return {"user": user, "ten": ten, "role": role}
    except Exception:
        return None

# CSS toàn cục (luôn load — cần thiết cho cả trang login lẫn app)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; background-color: #0f1117; color: #e0e0e0; }
.sys-header { background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%); border-bottom: 2px solid #00e5a0; padding: 18px 28px; margin: -1rem -1rem 1.5rem -1rem; display: flex; align-items: center; justify-content: space-between; }
.sys-header-left { display:flex; align-items:center; gap:14px; }
.sys-header h1 { font-family: 'IBM Plex Mono', monospace; font-size: 1.3rem; color: #00e5a0; margin: 0; letter-spacing: 2px; text-transform: uppercase; }
.sys-header .dot { width: 10px; height: 10px; border-radius: 50%; background: #00e5a0; box-shadow: 0 0 10px #00e5a0; animation: pulse 2s infinite; }
.user-badge { background:#1a1f2e; border:1px solid #2a3045; border-radius:20px; padding:6px 14px; font-size:0.8rem; color:#00e5a0; font-family:'IBM Plex Mono',monospace; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
.card { background: #1a1f2e; border: 1px solid #2a3045; border-radius: 10px; padding: 20px; margin-bottom: 16px; }
.card-title { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: #00e5a0; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 14px; border-bottom: 1px solid #2a3045; padding-bottom: 8px; }
.badge-doing { background: #1a2e1a; color: #4ade80; border: 1px solid #4ade80; padding: 3px 10px; border-radius: 20px; font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
.job-row { background: #1a1f2e; border: 1px solid #2a3045; border-left: 3px solid #f59e0b; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; }
.job-headcode { font-family: 'IBM Plex Mono', monospace; font-size: 1rem; font-weight: 600; color: #f59e0b; }
.job-meta { font-size: 0.78rem; color: #94a3b8; margin-top: 2px; }
.login-wrap { min-height: 80vh; display: flex; align-items: center; justify-content: center; }
.login-box { width: 100%; max-width: 400px; padding: 40px; background: #1a1f2e; border: 1px solid #2a3045; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,229,160,0.08); }
.login-title { font-family:'IBM Plex Mono',monospace; color:#00e5a0; font-size:1.2rem; text-align:center; margin-bottom:28px; letter-spacing:2px; }
.login-logo { text-align:center; margin-bottom:24px; }
.login-logo-text { font-family:'IBM Plex Mono',monospace; font-size:1.6rem; color:#00e5a0; letter-spacing:4px; }
.login-logo-sub { color:#64748b; font-size:0.85rem; margin-top:6px; }
.stTextInput input { background: #0f1117 !important; border: 1px solid #2a3045 !important; color: #e0e0e0 !important; border-radius: 6px !important; font-family: 'IBM Plex Mono', monospace !important; }
.stTextInput input:focus { border-color: #00e5a0 !important; box-shadow: 0 0 0 2px rgba(0,229,160,0.15) !important; }
.stTextInput input:disabled, .stTextInput input[disabled] { background: #1a1f2e !important; color: #00e5a0 !important; border: 1px solid #00e5a0 !important; -webkit-text-fill-color: #00e5a0 !important; opacity: 1 !important; cursor: default !important; font-weight: 600 !important; }
.stFormSubmitButton button { background: linear-gradient(135deg, #00e5a0, #00b37e) !important; color: #0f1117 !important; font-family: 'IBM Plex Mono', monospace !important; font-weight: 700 !important; font-size: 0.95rem !important; border: none !important; border-radius: 8px !important; height: 48px !important; }
.stFormSubmitButton button:hover { opacity: 0.9 !important; transform: translateY(-1px); }
.stAlert { border-radius: 8px !important; }
div[data-testid="stFileUploaderDropzone"] { padding: 10px !important; }
</style>
""", unsafe_allow_html=True)

# =====================================================
# API FUNCTIONS
# =====================================================
DATA_CACHE_TTL = 86400

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def fetch_init_data():
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"init"}, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                hc_dict = {}
                for row in data.get("records", []):
                    hc = str(row[0]).strip()
                    if hc:
                        hc_dict[hc] = {"ten_cong_trinh": row[1], "ten_san_pham": row[2]}
                return {"active_jobs_raw": data.get("active_jobs",[]), "hc_dict": hc_dict,
                        "loaded_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")}
    except Exception:
        pass
    return None

def fetch_active_jobs_from_sheet():
    try:
        resp = requests.get(WEB_APP_URL + "?action=get_active", timeout=15)
        if resp.status_code == 200:
            jobs = {}
            for item in resp.json().get("active_jobs", []):
                jk = f"{item['headcode']}|{item['congdoan']}|{item['nguoibao'].strip().lower()}"
                jobs[jk] = item
            return jobs
    except Exception:
        pass
    return {}

def call_api(payload):
    try:
        resp = requests.post(WEB_APP_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            return True, resp.json()
        return False, {"message": f"HTTP {resp.status_code}"}
    except Exception as ex:
        return False, {"message": str(ex)}

def api_change_password(user: str, old_pass: str, new_pass: str):
    """Đổi mật khẩu người dùng qua Apps Script."""
    try:
        resp = requests.post(WEB_APP_URL, json={
            "action":   "change_password",
            "user":     user,
            "old_pass": old_pass,
            "new_pass": new_pass,
        }, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as ex:
        return {"status": "error", "message": str(ex)}
    return {"status": "error", "message": "Không thể kết nối"}

def lookup_in_cache(headcode: str):
    init = fetch_init_data()
    if init is None:
        return None
    info = init["hc_dict"].get(str(headcode).strip())
    return {"status":"found", **info} if info else {"status":"not_found"}

def do_login(user: str, password: str):
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"login","user":user,"pass":password}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def search_qr_log(query: str):
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"search","query":query.strip()}, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("results", [])
    except Exception:
        pass
    return None

# =====================================================
# SESSION STATE
# =====================================================
# Khởi tạo session state — chỉ set nếu key chưa tồn tại
# "logged_in" mặc định False → bắt buộc qua trang login mỗi phiên mới
defaults = {
    # Auth — QUAN TRỌNG: logged_in phải là False khi chưa xác thực
    "logged_in":          False,
    "current_user":       "",
    "current_ten":        "",
    "login_error":        "",
    # App state
    "qr_detected":        "",
    "headcode_val":       "",
    "nguoibao_val":       "",
    "congdoan_val":       DANH_SACH_CONG_DOAN[0],
    "congdoan_tiep_val":  "",
    "soluong_val":        "",
    "form_key":           0,
    "active_jobs":        {},
    "active_jobs_loaded": False,
    "last_action":        None,
    "last_submit_key":    "",
    "last_submit_time":   0.0,
    "lookup_headcode":    "",
    "lookup_result":      None,
    "prefill_headcode":   "",
    "prefill_nguoibao":   "",
    "prefill_congdoan":   "",
    "prefill_soluong":    "",
    "search_query":       "",
    "search_results":     [],
    "current_role":       "",   # "sản xuất" | "người xem"
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =====================================================
# GUARD + QUERY PARAMS RESTORE — đồng bộ, không cần JS timing
# =====================================================
if not st.session_state.get("logged_in"):
    saved = read_session()
    if saved:
        st.session_state.logged_in          = True
        st.session_state.current_user       = saved["user"]
        st.session_state.current_ten        = saved["ten"]
        st.session_state.current_role       = saved.get("role", "")
        st.session_state.nguoibao_val       = saved["ten"]
        st.session_state.active_jobs_loaded = False

# =====================================================
# TRANG ĐĂNG NHẬP — chặn toàn bộ nội dung phía dưới nếu chưa login
# =====================================================
if not st.session_state.logged_in:
    st.markdown("""
    <div style="max-width:420px; margin:60px auto 0 auto; text-align:center;">
        <div style="font-family:'IBM Plex Mono',monospace; font-size:1.6rem;
                    color:#00e5a0; letter-spacing:4px; margin-bottom:6px;">⚙ HỆ THỐNG QR</div>
        <div style="color:#64748b; font-size:0.85rem; margin-bottom:32px;">Xưởng Sản Xuất — Vui lòng đăng nhập</div>
    </div>
    """, unsafe_allow_html=True)

    _, col_center, _ = st.columns([1, 1.2, 1])
    with col_center:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="login-title">🔐 ĐĂNG NHẬP</div>', unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            user_input = st.text_input("👤 Tên đăng nhập", placeholder="Nhập username...")
            pass_input = st.text_input("🔑 Mật khẩu", type="password", placeholder="Nhập mật khẩu...")
            login_btn  = st.form_submit_button("▶ ĐĂNG NHẬP", use_container_width=True)

        if st.session_state.login_error:
            st.error(st.session_state.login_error)

        if login_btn:
            if not user_input.strip() or not pass_input.strip():
                st.session_state.login_error = "⚠️ Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu."
                st.rerun()
            else:
                with st.spinner("Đang xác thực..."):
                    result = do_login(user_input.strip(), pass_input.strip())
                if result and result.get("status") == "ok":
                    _user = result.get("user", user_input.strip())
                    _ten  = result.get("ten",  user_input.strip())
                    _role = result.get("role", "").strip().lower()
                    # Lưu session vào query_params (đồng bộ, 30 ngày)
                    save_session(_user, _ten, _role)
                    st.session_state.logged_in          = True
                    st.session_state.current_user       = _user
                    st.session_state.current_ten        = _ten
                    st.session_state.current_role       = _role
                    st.session_state.nguoibao_val       = _ten
                    st.session_state.login_error        = ""
                    st.session_state.active_jobs_loaded = False
                    st.rerun()
                elif result:
                    st.session_state.login_error = f"❌ {result.get('message', 'Sai tên đăng nhập hoặc mật khẩu')}"
                    st.rerun()
                else:
                    st.session_state.login_error = "❌ Không thể kết nối tới máy chủ. Vui lòng thử lại."
                    st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # QUAN TRỌNG: st.stop() dừng render — không cho hiện app khi chưa login
    st.stop()

# =====================================================
# ĐÃ ĐĂNG NHẬP — HEADER
# =====================================================
col_h1, col_h2 = st.columns([3,1])
with col_h1:
    st.markdown("""
    <div class="sys-header">
        <div class="sys-header-left">
            <div class="dot"></div>
            <h1>⚙ Hệ Thống Quét QR Xưởng Sản Xuất</h1>
        </div>
    </div>""", unsafe_allow_html=True)
with col_h2:
    _norm = normalize_role(st.session_state.current_role)
    _role_label = "🏭 SẢN XUẤT" if _norm == "sanxuat" else "👁 NGƯỜI XEM"
    _role_color = "#00e5a0"     if _norm == "sanxuat" else "#f59e0b"
    st.markdown(f"""
    <div style="padding:18px 0; text-align:right; display:flex; gap:8px; justify-content:flex-end; align-items:center;">
        <span class="user-badge">👤 {st.session_state.current_ten}</span>
        <span style="background:#1a1f2e; border:1px solid {_role_color}; border-radius:20px;
                     padding:6px 14px; font-size:0.75rem; color:{_role_color};
                     font-family:'IBM Plex Mono',monospace;">{_role_label}</span>
    </div>""", unsafe_allow_html=True)
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔑 Đổi mật khẩu", use_container_width=True):
            st.session_state.show_change_pass = not st.session_state.get("show_change_pass", False)
            st.rerun()
    with col_btn2:
        if st.button("🚪 Đăng xuất", use_container_width=True):
            clear_session()
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # ── Form đổi mật khẩu (hiện/ẩn theo toggle) ──
    if st.session_state.get("show_change_pass"):
        with st.form("form_change_pass", clear_on_submit=True):
            st.markdown("""
            <div style="background:#1a1f2e; border:1px solid #00e5a0; border-radius:8px;
                        padding:12px 16px; margin-bottom:8px;">
                <div style="font-family:'IBM Plex Mono',monospace; color:#00e5a0;
                            font-size:0.7rem; letter-spacing:2px;">🔑 ĐỔI MẬT KHẨU</div>
            </div>""", unsafe_allow_html=True)
            old_pass  = st.text_input("Mật khẩu hiện tại", type="password", key="cp_old")
            new_pass  = st.text_input("Mật khẩu mới", type="password", key="cp_new")
            new_pass2 = st.text_input("Xác nhận mật khẩu mới", type="password", key="cp_new2")
            submit_cp = st.form_submit_button("💾 Xác nhận đổi", use_container_width=True)

        if submit_cp:
            if not old_pass or not new_pass or not new_pass2:
                st.error("Vui lòng điền đầy đủ thông tin.")
            elif new_pass != new_pass2:
                st.error("❌ Mật khẩu mới không khớp.")
            elif len(new_pass) < 4:
                st.error("❌ Mật khẩu mới phải có ít nhất 4 ký tự.")
            elif new_pass == old_pass:
                st.error("❌ Mật khẩu mới phải khác mật khẩu cũ.")
            else:
                with st.spinner("Đang cập nhật..."):
                    result = api_change_password(
                        st.session_state.current_user, old_pass, new_pass)
                if result.get("status") == "ok":
                    st.success("✅ Đổi mật khẩu thành công!")
                    st.session_state.show_change_pass = False
                    st.rerun()
                else:
                    st.error(f"❌ {result.get('message', 'Lỗi không xác định')}")

# =====================================================
# LOAD INIT DATA (lần đầu)
# =====================================================
if not st.session_state.active_jobs_loaded:
    with st.spinner("🔄 Đang khởi động hệ thống..."):
        init_data = fetch_init_data()
        if init_data:
            jobs = {}
            for item in init_data.get("active_jobs_raw", []):
                jk = f"{item['headcode']}|{item['congdoan']}|{item['nguoibao'].strip().lower()}"
                jobs[jk] = item
            st.session_state.active_jobs = jobs
        st.session_state.active_jobs_loaded = True

# =====================================================
# PREFILL TỪ DANH SÁCH
# =====================================================
if st.session_state.prefill_headcode:
    st.session_state.qr_detected     = st.session_state.prefill_headcode
    st.session_state.headcode_val    = st.session_state.prefill_headcode
    st.session_state.congdoan_val    = st.session_state.prefill_congdoan
    st.session_state.soluong_val     = st.session_state.prefill_soluong
    st.session_state.prefill_headcode = ""
    st.session_state.prefill_nguoibao = ""
    st.session_state.prefill_congdoan = ""
    st.session_state.prefill_soluong  = ""
    st.session_state.form_key += 1
    st.rerun()

# =====================================================
# REALTIME JOB STATE
# =====================================================
def get_current_job_state():
    hc = st.session_state.headcode_val.strip()
    cd = st.session_state.congdoan_val
    nb = st.session_state.current_ten.strip()
    if hc and nb:
        jk = f"{hc}|{cd}|{nb.lower()}"
        return jk, jk in st.session_state.active_jobs
    return "", False

# =====================================================
# LAYOUT
# =====================================================
col_scan, col_active = st.columns([1.1, 0.9], gap="large")

# ─────────────────────────────────────────────────
# CỘT TRÁI
# ─────────────────────────────────────────────────
with col_scan:
    # ── Kiểm tra quyền ──
    _is_san_xuat = normalize_role(st.session_state.current_role) == "sanxuat"

    if not _is_san_xuat:
        st.markdown("""
        <div style="background:#2d1a0a; border:1px solid #f59e0b; border-radius:10px;
                    padding:20px 24px; text-align:center; margin-bottom:16px;">
            <div style="font-family:'IBM Plex Mono',monospace; color:#f59e0b;
                        font-size:1rem; letter-spacing:2px; margin-bottom:8px;">👁 CHẾ ĐỘ XEM</div>
            <div style="color:#94a3b8; font-size:0.85rem;">
                Tài khoản của bạn chỉ có quyền <b style="color:#f59e0b">tra cứu</b>.<br/>
                Liên hệ quản trị viên để được cấp quyền sản xuất.
            </div>
        </div>""", unsafe_allow_html=True)

    if _is_san_xuat:
        # Camera — bật/tắt bằng nút, quét realtime không cần chụp ảnh
        st.markdown('<div class="card"><div class="card-title">📷 Quét mã QR</div>', unsafe_allow_html=True)

        # Nút bật/tắt camera
        if not st.session_state.get("scanner_open", False):
            if st.button("📷 Mở camera quét QR", use_container_width=True,
                         key=f"open_cam_{st.session_state.form_key}"):
                st.session_state.scanner_open = True
                st.rerun()
        else:
            if st.button("✖️ Đóng camera", use_container_width=True,
                         key=f"close_cam_{st.session_state.form_key}"):
                st.session_state.scanner_open = False
                st.rerun()
            # QR scanner realtime — chỉ render khi đang mở
            qr_result = qrcode_scanner(key=f"qr_scanner_{st.session_state.form_key}")
            if qr_result and qr_result != st.session_state.qr_detected:
                st.session_state.qr_detected     = qr_result
                st.session_state.headcode_val    = qr_result
                result = lookup_in_cache(qr_result)
                st.session_state.lookup_headcode = qr_result
                st.session_state.lookup_result   = result
                st.session_state.scanner_open    = False  # Tự đóng camera sau khi quét
                st.session_state.form_key += 1
                st.rerun()

    if st.session_state.lookup_result and st.session_state.lookup_result.get("status") == "found":
        r = st.session_state.lookup_result
        st.success(f"✅ **{st.session_state.lookup_headcode}** — {r.get('ten_san_pham','')}")
    elif st.session_state.lookup_headcode and st.session_state.lookup_result and st.session_state.lookup_result.get("status") == "not_found":
        st.error(f"❌ Mã **{st.session_state.lookup_headcode}** không tồn tại!")
    st.markdown('</div>', unsafe_allow_html=True)

    # Form
    st.markdown('<div class="card"><div class="card-title">📝 Thông tin thao tác</div>', unsafe_allow_html=True)

    # Thông tin sản phẩm
    if st.session_state.lookup_result and st.session_state.lookup_result.get("status") == "found":
        r = st.session_state.lookup_result
        st.markdown(f"""
        <div style="background:#0f2d1f; border:1px solid #00e5a0; border-radius:8px;
                    padding:10px 14px; margin-bottom:12px; font-size:0.82rem;">
            <div style="color:#00e5a0; font-family:IBM Plex Mono,monospace;
                        font-size:0.7rem; letter-spacing:1px; margin-bottom:6px;">📦 THÔNG TIN SẢN PHẨM</div>
            <div style="color:#e0e0e0;"><b>Công trình:</b> {r.get('ten_cong_trinh','')}</div>
            <div style="color:#e0e0e0; margin-top:4px;"><b>Sản phẩm:</b> {r.get('ten_san_pham','')}</div>
        </div>""", unsafe_allow_html=True)

    # ── Công đoạn hiện tại ──
    _cd_key = f"_congdoan_{st.session_state.form_key}"
    def on_congdoan_change():
        st.session_state.congdoan_val      = st.session_state[_cd_key]
        st.session_state.congdoan_tiep_val = ""
    st.selectbox("Công đoạn hiện tại *", options=DANH_SACH_CONG_DOAN,
        index=DANH_SACH_CONG_DOAN.index(st.session_state.congdoan_val)
              if st.session_state.congdoan_val in DANH_SACH_CONG_DOAN else 0,
        key=_cd_key, on_change=on_congdoan_change)

    # ── Công đoạn tiếp theo (loại trừ công đoạn hiện tại) ──
    _cd_tiep_opts = ["-- Chọn công đoạn tiếp theo --"] + [
        cd for cd in DANH_SACH_CONG_DOAN if cd != st.session_state.congdoan_val
    ]
    _cd_tiep_key = f"_congdoan_tiep_{st.session_state.form_key}"
    def on_cd_tiep_change():
        v = st.session_state[_cd_tiep_key]
        st.session_state.congdoan_tiep_val = "" if v.startswith("--") else v
    _tiep_idx = 0
    if st.session_state.congdoan_tiep_val in _cd_tiep_opts:
        _tiep_idx = _cd_tiep_opts.index(st.session_state.congdoan_tiep_val)
    st.selectbox("Công đoạn tiếp theo *", options=_cd_tiep_opts,
        index=_tiep_idx, key=_cd_tiep_key, on_change=on_cd_tiep_change)

    # ── Người vận hành: hiển thị readonly (từ tài khoản đăng nhập) ──
    st.text_input("Người vận hành", value=st.session_state.current_ten,
                  disabled=True, key=f"nb_display_{st.session_state.form_key}")

    # Banner trạng thái
    job_key_live, is_active_live = get_current_job_state()
    if not st.session_state.headcode_val.strip():
        st.info("📷 Quét QR hoặc nhập tay Headcode")
    elif is_active_live:
        job_info = st.session_state.active_jobs[job_key_live]
        st.warning(f"🔄 Đang làm từ **{job_info['gio_bat_dau']}** → Xác nhận **HOÀN THÀNH**")
    else:
        st.info(f"🚀 Chưa bắt đầu → Xác nhận **BẮT ĐẦU**")
    mode_label = "🏁 HOÀN THÀNH" if is_active_live else "▶️ BẮT ĐẦU"

    # ── Headcode (ngoài form, realtime lookup) ──
    _hc_key = f"_headcode_{st.session_state.form_key}"
    def on_headcode_change():
        new_hc = st.session_state[_hc_key].strip()
        st.session_state.headcode_val = new_hc
        st.session_state.qr_detected  = new_hc
        if new_hc:
            result = lookup_in_cache(new_hc)
            st.session_state.lookup_headcode = new_hc
            st.session_state.lookup_result   = result
        else:
            st.session_state.lookup_headcode = ""
            st.session_state.lookup_result   = None

    st.text_input("Headcode *", value=st.session_state.headcode_val,
        key=_hc_key, on_change=on_headcode_change,
        placeholder="Quét QR hoặc nhập tay...")

    # Fallback lookup nếu chưa lookup
    hc_live = st.session_state.headcode_val.strip()
    if hc_live and hc_live != st.session_state.lookup_headcode:
        result = lookup_in_cache(hc_live)
        st.session_state.lookup_headcode = hc_live
        st.session_state.lookup_result   = result

    with st.form(key=f"main_form_{st.session_state.form_key}", clear_on_submit=False):
        headcode = st.session_state.headcode_val.strip()
        soluong_str = st.text_input("Số lượng", value=st.session_state.soluong_val,
            placeholder="Nhập số lượng...",
            key=f"soluong_{st.session_state.form_key}")
        try:
            soluong = float(soluong_str.replace(",",".")) if soluong_str.strip() else None
        except ValueError:
            soluong = None
        submit = st.form_submit_button(
            label=f"💾 XÁC NHẬN — {mode_label}", use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── SUBMIT ──
    if submit:
        nguoibao = st.session_state.current_ten.strip()  # Luôn lấy từ tài khoản
        congdoan  = st.session_state.congdoan_val

        _submit_key = f"{headcode}|{congdoan}|{nguoibao}"
        _now = time.time()
        _is_dup = (_submit_key == st.session_state.last_submit_key and
                   (_now - st.session_state.last_submit_time) < 5.0)
        if not _is_dup:
            st.session_state.last_submit_key  = _submit_key
            st.session_state.last_submit_time = _now

        if _is_dup:
            st.warning("⚠️ Thao tác vừa được ghi nhận, vui lòng chờ...")
        elif not headcode:
            st.error("Vui lòng quét hoặc điền Headcode.")
        elif soluong is None:
            st.error("Vui lòng nhập số lượng hợp lệ.")
        elif headcode != st.session_state.lookup_headcode:
            st.error("❌ Headcode chưa được kiểm tra. Vui lòng nhập lại.")
            st.session_state.headcode_val = ""; st.session_state.lookup_headcode = ""
            st.session_state.lookup_result = None; st.session_state.form_key += 1
            st.rerun()
        elif not st.session_state.lookup_result or st.session_state.lookup_result.get("status") != "found":
            st.error("❌ Headcode không hợp lệ.")
            st.session_state.headcode_val = ""; st.session_state.lookup_headcode = ""
            st.session_state.lookup_result = None; st.session_state.form_key += 1
            st.rerun()
        else:
            congdoan_tiep = st.session_state.congdoan_tiep_val.strip()
            job_key   = f"{headcode}|{congdoan}|{nguoibao.lower()}"
            is_active = job_key in st.session_state.active_jobs

            # Bắt buộc chọn công đoạn tiếp theo khi HOÀN THÀNH
            if is_active and not congdoan_tiep:
                st.error("❌ Vui lòng chọn Công đoạn tiếp theo trước khi hoàn thành.")
            elif not is_active:
                _lr = st.session_state.lookup_result or {}
                payload = {
                    "action":          "start",
                    "headcode":        headcode,
                    "ten_cong_trinh":  _lr.get("ten_cong_trinh", ""),
                    "ten_san_pham":    _lr.get("ten_san_pham", ""),
                    "congdoan":        congdoan,
                    "soluong":         soluong,
                    "nguoibao":        nguoibao,
                }
                with st.spinner("Đang ghi nhận bắt đầu..."):
                    ok, resp_data = call_api(payload)
                if ok and resp_data.get("status") == "ok":
                    st.session_state.active_jobs[job_key] = {
                        "headcode":headcode,"congdoan":congdoan,"nguoibao":nguoibao,
                        "soluong":soluong,"gio_bat_dau":resp_data.get("gio_bat_dau",""),
                        "row_id":resp_data.get("row_id",""),
                    }
                    st.session_state.last_action = {"type":"start","headcode":headcode,"congdoan":congdoan}
                    st.session_state.qr_detected = ""; st.session_state.headcode_val = ""
                    st.session_state.lookup_headcode = ""; st.session_state.lookup_result = None
                    st.session_state.soluong_val = ""; st.session_state.form_key += 1
                    st.rerun()
                elif resp_data.get("status") == "duplicate":
                    st.warning("⚠️ Mã đã được ghi nhận. Đang đồng bộ...")
                    st.session_state.active_jobs = fetch_active_jobs_from_sheet()
                    st.session_state.form_key += 1; st.rerun()
                else:
                    st.error(f"Lỗi: {resp_data.get('message','Không rõ')}")
            elif is_active:
                job_info = st.session_state.active_jobs[job_key]
                payload  = {"action":"finish","headcode":headcode,"congdoan":congdoan,
                            "congdoan_tiep": congdoan_tiep,
                            "soluong":soluong,"nguoibao":nguoibao,
                            "gio_bat_dau":job_info["gio_bat_dau"],
                            "gio_hoan_thanh":datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M:%S"),
                            "row_id":job_info.get("row_id","")}
                with st.spinner("Đang cập nhật hoàn thành..."):
                    ok, resp_data = call_api(payload)
                if ok and resp_data.get("status") == "ok":
                    del st.session_state.active_jobs[job_key]
                    st.session_state.last_action = {"type":"finish","headcode":headcode,"congdoan":congdoan}
                    st.session_state.qr_detected = ""; st.session_state.headcode_val = ""
                    st.session_state.lookup_headcode = ""; st.session_state.lookup_result = None
                    st.session_state.soluong_val = ""; st.session_state.congdoan_tiep_val = ""
                    st.session_state.form_key += 1
                    st.rerun()
                else:
                    st.error(f"Lỗi: {resp_data.get('message','Không rõ')}")

    # end if _is_san_xuat

# ─────────────────────────────────────────────────
# CỘT PHẢI
# ─────────────────────────────────────────────────
with col_active:
    if st.session_state.last_action:
        act = st.session_state.last_action
        if act["type"] == "start":
            st.success(f"🚀 ĐÃ BẮT ĐẦU: **{act['headcode']}** — {act['congdoan']}")
        else:
            st.success(f"🏁 ĐÃ HOÀN THÀNH: **{act['headcode']}** — {act['congdoan']}")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🔄 Làm mới danh sách", use_container_width=True):
            st.session_state.active_jobs = fetch_active_jobs_from_sheet()
            st.rerun()
    with col_r2:
        if st.button("🗄️ Làm mới dữ liệu DATA", use_container_width=True):
            fetch_init_data.clear()
            st.session_state.lookup_headcode = ""; st.session_state.lookup_result = None
            st.success("✅ Đã xóa cache!"); st.rerun()

    init_info = fetch_init_data()
    loaded_at = init_info["loaded_at"] if init_info else None
    if loaded_at:
        st.markdown(f'<div style="font-size:0.72rem; color:#64748b; text-align:center; margin-bottom:8px;">'
                    f'🗄️ DATA: <b style="color:#94a3b8">{loaded_at}</b> | Tự làm mới sau 24h</div>',
                    unsafe_allow_html=True)

    # Danh sách đang xử lý
    st.markdown('<div class="card"><div class="card-title">⚡ Đang xử lý</div>', unsafe_allow_html=True)
    active_jobs = st.session_state.active_jobs
    if not active_jobs:
        st.markdown('<p style="color:#64748b; font-size:0.85rem; font-family:IBM Plex Mono,monospace;">— Chưa có công việc nào —</p>', unsafe_allow_html=True)
    else:
        for jk, job in list(active_jobs.items()):
            # ── Thông tin job ──
            st.markdown(f"""
            <div class="job-row">
                <div class="job-headcode">{job['headcode']}</div>
                <div class="job-meta">{job['congdoan']}</div>
                <div class="job-meta">👤 {job['nguoibao']} | 📦 {job.get('soluong',0)}</div>
                <div class="job-meta" style="color:#64748b;font-size:0.72rem;">🕐 {job['gio_bat_dau']}</div>
            </div>""", unsafe_allow_html=True)

            # ── Hàng 1: Giờ HC + Giờ TC + Nút Nhập Giờ ──
            c_hc, c_tc, c_nhap_gio = st.columns([1, 1, 1])
            with c_hc:
                gio_hc = st.text_input("⏱ Giờ HC",
                    value=st.session_state.get(f"gio_hc_{jk}", ""),
                    placeholder="0.00",
                    key=f"inp_hc_{jk}_{st.session_state.form_key}",
                    label_visibility="visible")
            with c_tc:
                gio_tc = st.text_input("🌙 Giờ TC",
                    value=st.session_state.get(f"gio_tc_{jk}", ""),
                    placeholder="0.00",
                    key=f"inp_tc_{jk}_{st.session_state.form_key}",
                    label_visibility="visible")
            with c_nhap_gio:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                _gio_submitted = st.session_state.get(f"gio_submitted_{jk}", False)
                if st.button(
                    "✔ Đã ghi" if _gio_submitted else "📥 Nhập giờ",
                    key=f"nhap_gio_{jk}",
                    use_container_width=True,
                    disabled=_gio_submitted,
                ):
                    # ✅ Set flag NGAY ĐẦU TIÊN trước mọi xử lý
                    # → mọi lần bấm tiếp theo trong cùng render cycle đều bị chặn
                    st.session_state[f"gio_submitted_{jk}"] = True

                    # Kiểm tra đúng người
                    job_nguoi   = job["nguoibao"].strip().lower()
                    login_nguoi = st.session_state.current_ten.strip().lower()
                    if job_nguoi != login_nguoi:
                        st.session_state[f"gio_err_{jk}"]        = True
                        st.session_state[f"gio_submitted_{jk}"]  = False
                        st.rerun()

                    # Parse giá trị
                    try:
                        val_hc = float(str(gio_hc).replace(",",".")) if str(gio_hc).strip() else None
                    except ValueError:
                        val_hc = None
                    try:
                        val_tc = float(str(gio_tc).replace(",",".")) if str(gio_tc).strip() else None
                    except ValueError:
                        val_tc = None

                    if val_hc is None and val_tc is None:
                        st.session_state[f"gio_submitted_{jk}"] = False
                        st.warning("⚠️ Vui lòng nhập ít nhất 1 giá trị giờ công.")
                    else:
                        row_id = job.get("row_id", "")
                        payload_gio = {
                            "action":   "update_gio_cong",
                            "row_id":   row_id,
                            "headcode": job["headcode"],
                            "congdoan": job["congdoan"],
                            "nguoibao": job["nguoibao"],
                            "gio_hc":   val_hc,
                            "gio_tc":   val_tc,
                        }
                        with st.spinner("Đang ghi giờ công..."):
                            ok, resp = call_api(payload_gio)
                        if ok and resp.get("status") == "ok":
                            st.session_state[f"gio_hc_{jk}"]        = ""
                            st.session_state[f"gio_tc_{jk}"]        = ""
                            st.session_state[f"gio_submitted_{jk}"] = False
                            st.session_state.form_key += 1
                            st.rerun()
                        elif resp.get("status") == "duplicate":
                            st.session_state[f"gio_hc_{jk}"]        = ""
                            st.session_state[f"gio_tc_{jk}"]        = ""
                            st.session_state[f"gio_submitted_{jk}"] = False
                            st.session_state.form_key += 1
                            st.rerun()
                        else:
                            st.session_state[f"gio_submitted_{jk}"] = False
                            st.error(f"Lỗi: {resp.get('message','Không rõ')}")

            # Cảnh báo sai người nhập giờ
            if st.session_state.get(f"gio_err_{jk}"):
                st.warning("⚠️ Mã hàng này không phải mã bạn đang làm")
                st.session_state.pop(f"gio_err_{jk}", None)

            # ── Hàng 2: Nút Xong ──
            c_xong, _ = st.columns([1, 2])
            with c_xong:
                if st.button("✅ Xong", key=f"finish_btn_{jk}", use_container_width=True):
                    job_nguoi   = job["nguoibao"].strip().lower()
                    login_nguoi = st.session_state.current_ten.strip().lower()
                    if job_nguoi != login_nguoi:
                        st.session_state[f"owner_err_{jk}"] = True
                    else:
                        st.session_state.pop(f"owner_err_{jk}", None)
                        sl = job.get("soluong","")
                        st.session_state.prefill_headcode = job["headcode"]
                        st.session_state.prefill_nguoibao = job["nguoibao"]
                        st.session_state.prefill_congdoan = job["congdoan"]
                        st.session_state.prefill_soluong  = str(sl) if sl != "" else ""
                    st.rerun()
                if st.session_state.get(f"owner_err_{jk}"):
                    st.warning("⚠️ Không phải mã của bạn")

            st.markdown("<hr style='border-color:#2a3045;margin:4px 0 12px 0'>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Hướng dẫn
    st.markdown("""
    <div class="card">
        <div class="card-title">📖 Hướng dẫn</div>
        <div style="font-size:0.82rem; color:#94a3b8; line-height:1.8;">
            <b style="color:#f59e0b">Lần quét 1</b> → <span style="color:#4ade80">BẮT ĐẦU</span><br/>
            <b style="color:#818cf8">Lần quét 2</b> → <span style="color:#818cf8">HOÀN THÀNH</span><br/>
            <b style="color:#00e5a0">Nút ✅ Xong</b> → Chọn nhanh từ danh sách<br/><br/>
            <span style="color:#64748b">⚠ Danh sách tự khôi phục khi mở lại app</span>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Tra cứu QR_Log ──
    st.markdown('<div class="card"><div class="card-title">🔍 Tra cứu lịch sử QR_Log</div>', unsafe_allow_html=True)

    def on_search_change():
        st.session_state.search_query   = st.session_state["_search_input"]
        st.session_state.search_results = []

    st.text_input("Nhập số đuôi headcode (3+ ký tự)",
        value=st.session_state.search_query, key="_search_input",
        on_change=on_search_change, placeholder="VD: 878 → tìm ...878")

    q = st.session_state.search_query.strip()
    if len(q) >= 3 and not st.session_state.search_results:
        with st.spinner("🔍 Đang tìm kiếm..."):
            rows = search_qr_log(q)
        if rows is None:
            st.error("❌ Không thể kết nối.")
        elif len(rows) == 0:
            st.info("Không tìm thấy kết quả nào.")
            st.session_state.search_results = ["__empty__"]
        else:
            st.session_state.search_results = rows

    results = st.session_state.search_results
    if results and results != ["__empty__"]:
        st.markdown(f'<div style="font-size:0.75rem;color:#00e5a0;margin-bottom:8px;">Tìm thấy <b>{len(results)}</b> kết quả</div>', unsafe_allow_html=True)
        st.markdown("""<div style="display:grid;grid-template-columns:1.2fr 1.5fr 0.6fr 0.8fr 1fr 1fr 0.7fr;
            gap:4px;padding:6px 8px;background:#0f1117;border-radius:6px;margin-bottom:4px;
            font-family:IBM Plex Mono,monospace;font-size:0.63rem;color:#64748b;text-transform:uppercase;">
            <div>Headcode</div><div>Công đoạn</div><div>SL</div><div>Người</div>
            <div>Bắt đầu</div><div>Hoàn thành</div><div>TT</div></div>""", unsafe_allow_html=True)
        for row in results:
            tt    = row.get("trang_thai","")
            color = "#4ade80" if tt=="ĐANG LÀM" else "#818cf8" if tt=="HOÀN THÀNH" else "#94a3b8"
            sl    = row.get("soluong","")
            try: sl = f"{float(sl):.3f}" if sl != "" else ""
            except: sl = str(sl)
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:1.2fr 1.5fr 0.6fr 0.8fr 1fr 1fr 0.7fr;
                gap:4px;padding:8px;background:#1a1f2e;border:1px solid #2a3045;
                border-left:3px solid {color};border-radius:6px;margin-bottom:4px;
                font-size:0.72rem;color:#e0e0e0;">
                <div style="font-family:IBM Plex Mono,monospace;color:#f59e0b;font-weight:600;">{row.get('headcode','')}</div>
                <div style="color:#94a3b8;font-size:0.65rem;">{row.get('congdoan','')}</div>
                <div>{sl}</div>
                <div style="color:#94a3b8;">{row.get('nguoibao','')}</div>
                <div style="font-size:0.63rem;">{row.get('gio_bat_dau','')}</div>
                <div style="font-size:0.63rem;">{row.get('gio_hoan_thanh','')}</div>
                <div style="color:{color};font-weight:600;font-size:0.65rem;">{tt}</div>
            </div>""", unsafe_allow_html=True)
    elif q and len(q) < 3:
        st.caption("Nhập ít nhất 3 số đuôi để tìm kiếm.")
    st.markdown('</div>', unsafe_allow_html=True)
