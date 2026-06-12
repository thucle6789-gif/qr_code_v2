import streamlit as st
import requests
import cv2
import numpy as np
from datetime import datetime, date
from zoneinfo import ZoneInfo
import time
import base64
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

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbwIX47mHQfQJdH3noDjp3xChyPHh3-5U9dM7DRiseoHwNai-uCuDQBy35Q__dqiUpU/exec"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Fallback nếu chưa load được từ server — đồng bộ với sheet CONG_DOAN
# Bao gồm nhóm để lọc được ngay cả khi server chưa trả về dữ liệu
DANH_SACH_CONG_DOAN_DEFAULT = [
    {"ten": "P013.1_CẮT CẦU",                          "nhom": "CTS"},
    {"ten": "P013.2_CẮT TIA NƯỚC",                     "nhom": "CTS"},
    {"ten": "P014.1_VÁT 45",                            "nhom": "CTS"},
    {"ten": "P014.2_CMS_PROFILE",                       "nhom": "CTS"},
    {"ten": "P014.3_CHẠY RON",                          "nhom": "CTS"},
    {"ten": "P015.1_CHÀ NHÁM CẠNH",                     "nhom": "TỔ ĐÁ"},
    {"ten": "P015.2_CHÀ NHÁM BỀ MẶT ( HONED )",         "nhom": "TỔ ĐÁ"},
    {"ten": "P015.3_ĐÁNH BÓNG MẶT",                     "nhom": "TỔ ĐÁ"},
    {"ten": "P016.1_GHÉP CẠNH ĐÁ 45 ĐỘ",               "nhom": "TỔ ĐÁ"},
    {"ten": "P016.2_GHÉP CẠNH ĐÁ DÁN CHỒNG NHIỀU LỚP", "nhom": "TỔ ĐÁ"},
    {"ten": "P017.1_ĐÁNH BÓNG CẠNH & MỐI GHÉP",        "nhom": "TỔ ĐÁ"},
    {"ten": "P017.2_LAYOUT SẢN PHẨM THỰC TẾ",          "nhom": "ĐÓNG KIỆN"},
    {"ten": "P018_CHỐNG THẤM",                          "nhom": "TỔ ĐÁ"},
    {"ten": "P019_VỆ SINH & DÁN DECAL BẢO VỆ",         "nhom": "TỔ ĐÁ"},
    {"ten": "P020_LẮP RÁP HOÀN THIỆN",                 "nhom": "TỔ ĐÁ"},
    {"ten": "P021_BAO BÌ ĐÓNG GÓI",                    "nhom": "ĐÓNG KIỆN"},
    {"ten": "P022_NHẬP KHO THÀNH PHẨM",                "nhom": "ĐÓNG KIỆN"},
    # TỔ KÍNH
    {"ten": "P013_Tạo phôi và Sơ chế",                 "nhom": "TỔ KÍNH"},
    {"ten": "P017_Làm nguội và Hoàn thiện",             "nhom": "TỔ KÍNH"},
    {"ten": "P019_Washing - Cleaning",                  "nhom": "TỔ KÍNH"},
    {"ten": "P20_Lắp ráp hoàn thiện",                  "nhom": "TỔ KÍNH"},
    {"ten": "P021_Đóng gói hoàn thành",                "nhom": "TỔ KÍNH"},
]

# =====================================================
# PAGE CONFIG & CSS
# =====================================================
st.set_page_config(page_title="Hệ Thống Quét QR Xưởng", layout="wide", initial_sidebar_state="collapsed")

# =====================================================
# QUẢN LÝ SESSION QUA localStorage (PWA-safe)
# Dùng st.query_params làm cầu nối:
#   - JS đọc localStorage → ghi vào URL params
#   - Python đọc URL params đồng bộ
#   - Hoạt động kể cả khi PWA reset URL về gốc
# =====================================================
SESSION_SECRET = "qr-xuong-2024-secret"

def compress_image(image_bytes: bytes, max_kb: int = 900) -> tuple[bytes, str]:
    """Nén ảnh xuống dưới max_kb KB. Trả về (bytes, mime_type)."""
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(image_bytes))

    # Chuyển sang RGB nếu cần (PNG có thể là RGBA)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize nếu quá lớn — tối đa 1920px cạnh dài
    max_side = 1920
    w, h = img.size
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # Nén JPEG với quality giảm dần cho đến khi < max_kb
    quality = 85
    while quality >= 30:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        size_kb = buf.tell() / 1024
        if size_kb <= max_kb:
            break
        quality -= 10

    buf.seek(0)
    return buf.read(), "image/jpeg"

def make_token(user: str, ten: str, ts: int) -> str:
    raw = f"{user}|{ten}|{ts}|{SESSION_SECRET}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def save_session(user: str, ten: str, role: str, nhom: str = ""):
    """Lưu session vào query_params (không dùng JS/localStorage)."""
    ts    = int(time.time())
    token = make_token(user, ten, ts)
    st.query_params.update({"t": token, "u": user, "n": ten,
                             "r": role, "g": nhom, "ts": str(ts)})

def clear_session():
    """Xóa session khỏi query_params."""
    st.query_params.clear()
def inject_session_from_localstorage():
    """Không dùng nữa."""
    pass

def read_session():
    """Đọc session từ query_params (đã được JS inject từ localStorage)."""
    try:
        p     = st.query_params
        token = p.get("t",  "")
        user  = p.get("u",  "")
        ten   = p.get("n",  "")
        role  = p.get("r",  "")
        ts    = int(p.get("ts", "0"))
        if not all([token, user, ten, ts]):
            return None
        if (time.time() - ts) > 30 * 86400:
            return None
        if make_token(user, ten, ts) != token:
            return None
        return {"user": user, "ten": ten, "role": role}
    except Exception:
        return None

# CSS toàn cục — Light blue theme
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap');

/* ── Reset & Base ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #f0f4f8;
    color: #1e293b;
}

/* ── Header ── */
.sys-header {
    background: linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%);
    border-bottom: none;
    padding: 16px 28px;
    margin: -1rem -1rem 1.5rem -1rem;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 4px 12px rgba(29,78,216,0.3);
}
.sys-header-left { display:flex; align-items:center; gap:14px; }
.sys-header h1 {
    font-family: 'Inter', sans-serif;
    font-size: 1.25rem; font-weight: 700;
    color: #ffffff; margin: 0; letter-spacing: 0.5px;
}
.sys-header-sub { color: rgba(255,255,255,0.75); font-size: 0.78rem; margin-top: 2px; }
.sys-header .dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: #4ade80; box-shadow: 0 0 8px #4ade80;
    animation: pulse 2s infinite;
}
.user-badge {
    background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.5);
    border-radius: 20px; padding: 6px 14px;
    font-size: 0.8rem; color: #ffffff; font-weight: 700;
    text-shadow: 0 1px 2px rgba(0,0,0,0.3);
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

/* ── Cards ── */
.card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.card-title {
    font-family: 'Inter', sans-serif;
    font-size: 0.8rem; font-weight: 700;
    color: #1d4ed8; letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 14px;
    border-bottom: 2px solid #eff6ff;
    padding-bottom: 8px;
}

/* ── Job row ── */
.job-row {
    background: #f8faff;
    border: 1px solid #dbeafe;
    border-left: 4px solid #f59e0b;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 10px;
}
.job-headcode {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1rem; font-weight: 600; color: #d97706;
}
.job-meta { font-size: 0.78rem; color: #64748b; margin-top: 3px; }

/* ── Badge ── */
.badge-doing {
    background: #dcfce7; color: #16a34a;
    border: 1px solid #86efac;
    padding: 3px 10px; border-radius: 20px;
    font-size: 0.7rem; font-weight: 600;
}

/* ── Login ── */
.login-wrap { min-height: 80vh; display: flex; align-items: center; justify-content: center; }
.login-box {
    width: 100%; max-width: 420px; padding: 40px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    box-shadow: 0 8px 32px rgba(29,78,216,0.1);
}
.login-title { color: #1d4ed8; font-size: 1.2rem; font-weight: 700; text-align: center; margin-bottom: 28px; }
.login-logo { text-align:center; margin-bottom:24px; }
.login-logo-text { font-size: 1.6rem; font-weight: 800; color: #1d4ed8; letter-spacing: 1px; }
.login-logo-sub { color: #94a3b8; font-size: 0.85rem; margin-top: 6px; }

/* ── Inputs ── */
.stTextInput input {
    background: #f8faff !important;
    border: 1.5px solid #cbd5e1 !important;
    color: #1e293b !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput input:focus {
    border-color: #1d4ed8 !important;
    box-shadow: 0 0 0 3px rgba(29,78,216,0.12) !important;
    background: #ffffff !important;
}
.stTextInput input:disabled, .stTextInput input[disabled] {
    background: #eff6ff !important;
    color: #1d4ed8 !important;
    border: 1.5px solid #bfdbfe !important;
    -webkit-text-fill-color: #1d4ed8 !important;
    opacity: 1 !important; font-weight: 600 !important;
}

/* ── Selectbox ── */
.stSelectbox > div > div {
    background: #f8faff !important;
    border: 1.5px solid #cbd5e1 !important;
    border-radius: 8px !important;
    color: #1e293b !important;
}

/* ── Buttons ── */
.stFormSubmitButton button, .stButton > button {
    background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
    color: #ffffff !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    border: none !important;
    border-radius: 8px !important;
    height: 46px !important;
    box-shadow: 0 2px 8px rgba(29,78,216,0.25) !important;
    transition: all 0.2s !important;
}
.stFormSubmitButton button:hover, .stButton > button:hover {
    opacity: 0.92 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(29,78,216,0.35) !important;
}

/* ── Alerts ── */
.stAlert { border-radius: 8px !important; }
div[data-testid="stFileUploaderDropzone"] { padding: 10px !important; }

/* ── Dividers ── */
hr { border-color: #e2e8f0 !important; }

/* ── Tạo khoảng cách giữa link buttons và nút camera ── */
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stButton"]) {
    margin-top: 12px;
}

/* ── Nút Đổi MK & Đăng xuất: không nền, nhỏ gọn ── */
/* Nhắm 2 nút trong _c_actions dùng :has() */
.action-row ~ div .stButton > button,
div[class*="action-row"] .stButton > button {
    background: transparent !important; border: none !important;
    box-shadow: none !important; color: #1d4ed8 !important;
    font-size: 0.78rem !important; height: 30px !important;
    font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)

# =====================================================
# API FUNCTIONS
# =====================================================
DATA_CACHE_TTL = 86400

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def fetch_init_data(cache_version: int = 0):
    _ = cache_version  # Chỉ dùng để bust cache
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"init"}, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                hc_dict = {}
                for row in data.get("records", []):
                    hc = str(row[0]).strip()
                    if hc:
                        hc_dict[hc] = {
                            "ten_cong_trinh": row[1] if len(row) > 1 else "",
                            "ten_san_pham":   row[2] if len(row) > 2 else "",
                            "dvt":            row[3] if len(row) > 3 else "",
                        }
                return {"active_jobs_raw": data.get("active_jobs",[]), "hc_dict": hc_dict,
                        "loaded_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")}
    except Exception:
        pass
    return None

def fetch_active_jobs_from_sheet():
    try:
        resp = requests.get(WEB_APP_URL + "?action=get_active", timeout=12)
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
        resp = requests.post(WEB_APP_URL, json=payload, timeout=12)
        if resp.status_code == 200:
            return True, resp.json()
        return False, {"message": f"HTTP {resp.status_code}"}
    except Exception as ex:
        return False, {"message": str(ex)}

def upload_image_to_sheet(row_id: str, headcode: str, congdoan: str,
                          nguoibao: str, image_bytes: bytes,
                          mime_type: str, file_name: str):
    """Upload ảnh base64 lên Drive qua Apps Script, ghi =IMAGE() vào ô H."""
    try:
        b64  = base64.b64encode(image_bytes).decode("utf-8")
        resp = requests.post(WEB_APP_URL, json={
            "action":       "upload_image",
            "row_id":       row_id,
            "headcode":     headcode,
            "congdoan":     congdoan,
            "nguoibao":     nguoibao,
            "image_base64": b64,
            "mime_type":    mime_type,
            "file_name":    file_name,
        }, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception as ex:
        return {"status": "error", "message": str(ex)}
    return {"status": "error", "message": "Không thể kết nối"}

def api_change_password(user: str, old_pass: str, new_pass: str):
    """Đổi mật khẩu người dùng qua Apps Script."""
    try:
        resp = requests.post(WEB_APP_URL, json={
            "action":   "change_password",
            "user":     user,
            "old_pass": old_pass,
            "new_pass": new_pass,
        }, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception as ex:
        return {"status": "error", "message": str(ex)}
    return {"status": "error", "message": "Không thể kết nối"}

def lookup_in_cache(headcode: str) -> dict:
    """Tra headcode trong DATA cache, nếu không có thì gọi API lookup trực tiếp."""
    hc = str(headcode).strip()
    if not hc:
        return {"status": "not_found"}
    # Thử cache DATA local
    init = fetch_init_data(st.session_state.get("cache_version", 0))
    if init:
        info = init["hc_dict"].get(hc)
        if info:
            return {"status": "found", **info}
    # Gọi trực tiếp API lookup
    try:
        resp = requests.get(WEB_APP_URL,
            params={"action": "lookup_headcode", "headcode": hc},
            timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "found":
                return {
                    "status":         "found",
                    "ten_cong_trinh": data.get("ten_cong_trinh", ""),
                    "ten_san_pham":   data.get("ten_san_pham", ""),
                    "dvt":            data.get("dvt", ""),
                }
    except Exception:
        pass
    return {"status": "not_found"}

def do_login(user: str, password: str):
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"login","user":user,"pass":password}, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def get_user_nhom(user: str) -> str:
    """Lấy nhóm của user từ sheet Nguoi_dung dựa vào username.
    Gọi khi restore session (reload trang) để lấy lại nhóm.
    """
    try:
        resp = requests.get(WEB_APP_URL,
            params={"action": "get_user_nhom", "user": user.strip()},
            timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                return data.get("nhom", "")
    except Exception:
        pass
    return ""

def search_qr_log(query: str):
    try:
        resp = requests.get(WEB_APP_URL, params={"action":"search","query":query.strip()}, timeout=12)
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
    "current_nhom":       "",
    "congdoan_list":      [],
    "current_user":       "",
    "current_ten":        "",
    "login_error":        "",
    # App state
    "qr_detected":        "",
    "headcode_val":       "",
    "nguoibao_val":       "",
    "congdoan_val":       "",   # Sẽ được set sau khi load danh sách công đoạn
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
# =====================================================
# XỬ LÝ ACTION TỪ LINK (doi_mk, dang_xuat) — PHẢI Ở TOP-LEVEL
_top_action = st.query_params.get("_action", "")
if _top_action == "doi_mk":
    st.session_state.show_change_pass = not st.session_state.get("show_change_pass", False)
    _qp2 = {k: v for k, v in dict(st.query_params).items() if k != "_action"}
    st.query_params.update(_qp2) if _qp2 else st.query_params.clear()
    if _qp2:
        st.query_params.update(_qp2)
    st.rerun()
elif _top_action == "dang_xuat":
    clear_session()
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# =====================================================
# GUARD + QUERY PARAMS RESTORE
# =====================================================
if not st.session_state.get("logged_in"):
    saved = read_session()
    if saved:
        st.session_state.logged_in          = True
        st.session_state.current_user       = saved["user"]
        st.session_state.current_ten        = saved["ten"]
        st.session_state.current_role       = saved.get("role", "")
        # Luôn lấy nhóm trực tiếp từ server khi restore — không phụ thuộc JS/localStorage
        _restored_nhom = get_user_nhom(saved["user"])
        st.session_state.current_nhom       = _restored_nhom
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
                    _nhom = result.get("nhom", "").strip()
                    save_session(_user, _ten, _role)
                    st.session_state.logged_in          = True
                    st.session_state.current_user       = _user
                    st.session_state.current_ten        = _ten
                    st.session_state.current_role       = _role
                    st.session_state.current_nhom       = _nhom
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
_norm_h   = normalize_role(st.session_state.current_role)
_rlabel_h = "🏭 SẢN XUẤT" if _norm_h == "sanxuat" else "👁 NGƯỜI XEM"
st.markdown(f"""
<div class="sys-header">
  <div class="sys-header-left">
    <div class="dot"></div>
    <div>
      <h1>🏭 Hệ Thống Quét QR Xưởng Sản Xuất</h1>
      <div class="sys-header-sub">Quản lý công đoạn sản xuất theo thời gian thực</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
    <span style="background:rgba(255,255,255,0.2);border:1.5px solid rgba(255,255,255,0.6);
                 border-radius:20px;padding:5px 14px;font-size:0.8rem;color:#fff;font-weight:700;">
      👤 {st.session_state.current_ten}
    </span>
    <span style="background:rgba(255,255,255,0.25);border:1.5px solid rgba(255,255,255,0.6);
                 border-radius:20px;padding:5px 14px;font-size:0.75rem;color:#fff;font-weight:700;">
      {_rlabel_h}
    </span>
  </div>
</div>""", unsafe_allow_html=True)

# Nút Đổi MK & Đăng xuất — nằm bên phải, dùng st.markdown + checkbox trick
_c_space, _c_actions = st.columns([3, 2])
with _c_actions:
    # Lấy URL hiện tại để tạo link
    _base_url = st.query_params
    _qstr = "&".join(f"{k}={v}" for k, v in dict(_base_url).items() if k != "_action")
    _url_mk = f"?{_qstr}&_action=doi_mk" if _qstr else "?_action=doi_mk"
    _url_dx = f"?{_qstr}&_action=dang_xuat" if _qstr else "?_action=dang_xuat"

    st.markdown(f"""
    <div style="display:flex; gap:8px; justify-content:flex-end;
                padding:2px 0 2px 0; margin-top:-8px; margin-bottom:4px;">
        <a href="{_url_mk}" target="_self" style="
            background:transparent; border:1.5px solid #93c5fd;
            border-radius:14px; padding:3px 12px;
            font-size:0.72rem; color:#1d4ed8; font-weight:600;
            text-decoration:none; white-space:nowrap;
            font-family:'Inter',sans-serif; line-height:1.8;">
            🔑 Đổi mật khẩu
        </a>
        <a href="{_url_dx}" target="_self" style="
            background:transparent; border:1.5px solid #93c5fd;
            border-radius:14px; padding:3px 12px;
            font-size:0.72rem; color:#1d4ed8; font-weight:600;
            text-decoration:none; white-space:nowrap;
            font-family:'Inter',sans-serif; line-height:1.8;">
            🚪 Đăng xuất
        </a>
    </div>""", unsafe_allow_html=True)

    # ── Form đổi mật khẩu (hiện/ẩn theo toggle) ──
    if st.session_state.get("show_change_pass"):
        with st.form("form_change_pass", clear_on_submit=True):
            st.markdown("""
            <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px;
                        padding:10px 14px; margin-bottom:8px;">
                <div style="font-family:'Inter',sans-serif; color:#1d4ed8;
                            font-size:0.8rem; font-weight:700;">🔑 ĐỔI MẬT KHẨU</div>
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
# Load congdoan_list LUÔN LUÔN từ cache (không phụ thuộc active_jobs_loaded)
# → đảm bảo khi bấm "Làm mới dữ liệu DATA", danh sách mới được apply ngay
_init_data_cached = fetch_init_data(st.session_state.get("cache_version", 0))
if _init_data_cached and not st.session_state.congdoan_list:
    st.session_state.congdoan_list = _init_data_cached.get("congdoan_list", [])

if not st.session_state.active_jobs_loaded:
    with st.spinner("🔄 Đang khởi động hệ thống..."):
        init_data = _init_data_cached
        if init_data:
            jobs = {}
            for item in init_data.get("active_jobs_raw", []):
                jk = f"{item['headcode']}|{item['congdoan']}|{item['nguoibao'].strip().lower()}"
                jobs[jk] = item
            st.session_state.active_jobs = jobs
            st.session_state.congdoan_list = init_data.get("congdoan_list", [])
        st.session_state.active_jobs_loaded = True

# Set congdoan_val về phần tử đầu tiên phù hợp nhóm nếu đang rỗng
if not st.session_state.congdoan_val:
    _nhom_init = st.session_state.get("current_nhom", "")
    _full = st.session_state.congdoan_list or DANH_SACH_CONG_DOAN_DEFAULT
    _ds_init = [item["ten"] for item in _full
                if not _nhom_init or item.get("nhom","").strip() == _nhom_init.strip()]
    if not _ds_init:
        _ds_init = [item["ten"] for item in _full]
    if _ds_init:
        st.session_state.congdoan_val = _ds_init[0]

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
def get_congdoan_list(nhom: str = "") -> list:
    """Lấy danh sách tên công đoạn, lọc theo nhóm nếu có.
    Dùng server data nếu có, fallback về DANH_SACH_CONG_DOAN_DEFAULT.
    Cả 2 đều là list of dict {ten, nhom}.
    """
    full_list = st.session_state.get("congdoan_list", [])
    if not full_list:
        full_list = DANH_SACH_CONG_DOAN_DEFAULT  # Fallback cũng là [{ten, nhom}]
    if nhom.strip():
        # Lọc chính xác theo nhóm
        filtered = [item["ten"] for item in full_list
                    if item.get("nhom","").strip() == nhom.strip()]
        # Nếu không có công đoạn nào khớp nhóm → hiện tất cả
        return filtered if filtered else [item["ten"] for item in full_list]
    # Không có nhóm → hiện tất cả
    return [item["ten"] for item in full_list]

def get_current_job_state():
    hc = st.session_state.headcode_val.strip()
    cd = st.session_state.congdoan_val or ""
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
        <div style="background:#fffbeb; border:1px solid #fbbf24; border-radius:10px;
                    padding:20px 24px; text-align:center; margin-bottom:16px;">
            <div style="font-family:'IBM Plex Mono',monospace; color:#d97706;
                        font-size:1rem; letter-spacing:2px; margin-bottom:8px;">👁 CHẾ ĐỘ XEM</div>
            <div style="color:#78716c; font-size:0.85rem;">
                Tài khoản của bạn chỉ có quyền <b style="color:#f59e0b">tra cứu</b>.<br/>
                Liên hệ quản trị viên để được cấp quyền sản xuất.
            </div>
        </div>""", unsafe_allow_html=True)

        # ── Bảng danh sách mã đang làm (chế độ xem) ──
        import pandas as pd
        import io as _io
        from datetime import datetime as _dt

        # Nút làm mới + tự động refresh mỗi 30s
        _vw_col1, _vw_col2 = st.columns([2, 3])
        with _vw_col1:
            if st.button("🔄 Làm mới danh sách", key="viewer_refresh",
                         use_container_width=True):
                st.session_state.pop("viewer_jobs_cache", None)
                st.rerun()
        with _vw_col2:
            st.markdown(
                f'<div style="font-size:0.75rem;color:#64748b;padding-top:10px;">'
                f'Tự làm mới mỗi 30 giây</div>',
                unsafe_allow_html=True
            )

        # Load trực tiếp từ API — fetch_active_jobs_from_sheet trả về dict
        _all_jobs = fetch_active_jobs_from_sheet() or {}

        # Lấy hc_dict từ fetch_init_data cache
        _init_view = fetch_init_data(st.session_state.get("cache_version", 0))
        _hc_dict   = _init_view.get("hc_dict", {}) if _init_view else {}

        rows_df = []
        for _jk, _job in _all_jobs.items():
            _hc   = _job.get("headcode", "")
            _info = _hc_dict.get(str(_hc).strip(), {})
            rows_df.append({
                "Headcode":          _hc,
                "Tên công trình":    _info.get("ten_cong_trinh", ""),
                "Tên sản phẩm":      _info.get("ten_san_pham", ""),
                "ĐVT":               _info.get("dvt", ""),
                "Công đoạn hiện tại": _job.get("congdoan", ""),
                "Số lượng":          _job.get("soluong", ""),
                "Người báo":         _job.get("nguoibao", ""),
                "Giờ bắt đầu":       _job.get("gio_bat_dau", ""),
            })

        if rows_df:
            df_jobs = pd.DataFrame(rows_df)
            st.markdown(f"**📋 Đang xử lý: {len(rows_df)} mã hàng**")
            st.dataframe(
                df_jobs,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Headcode":           st.column_config.TextColumn("Headcode",          width="small"),
                    "Tên công trình":     st.column_config.TextColumn("Tên công trình",    width="medium"),
                    "Tên sản phẩm":       st.column_config.TextColumn("Tên sản phẩm",      width="medium"),
                    "ĐVT":                st.column_config.TextColumn("ĐVT",               width="small"),
                    "Công đoạn hiện tại": st.column_config.TextColumn("Công đoạn",         width="medium"),
                    "Số lượng":           st.column_config.NumberColumn("Số lượng",        width="small"),
                    "Người báo":          st.column_config.TextColumn("Người báo",         width="medium"),
                    "Giờ bắt đầu":        st.column_config.TextColumn("Giờ bắt đầu",       width="medium"),
                },
                height=min(500, 44 + len(rows_df) * 36),
            )

            # Nút tải Excel
            _excel_buf = _io.BytesIO()
            with pd.ExcelWriter(_excel_buf, engine="openpyxl") as _writer:
                df_jobs.to_excel(_writer, index=False, sheet_name="Đang xử lý")
                _ws = _writer.sheets["Đang xử lý"]
                for _col in _ws.columns:
                    _max_len = max(len(str(_cell.value or "")) for _cell in _col) + 4
                    _ws.column_dimensions[_col[0].column_letter].width = min(_max_len, 45)
                # Freeze header row
                _ws.freeze_panes = "A2"
            _excel_buf.seek(0)
            _fname = f"dang_xu_ly_{_dt.now().strftime('%Y%m%d_%H%M')}.xlsx"
            st.download_button(
                label="📥 Tải file Excel",
                data=_excel_buf,
                file_name=_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.markdown('<p style="color:#64748b; font-size:0.85rem; font-family:IBM Plex Mono,monospace; margin-top:12px;">— Chưa có mã hàng nào đang xử lý —</p>', unsafe_allow_html=True)

    if _is_san_xuat:
        # Camera — bật/tắt bằng nút, quét realtime không cần chụp ảnh

        # Nút bật/tắt camera
        st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
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

    # Auto-lookup: chạy khi headcode thay đổi, chưa có kết quả, HOẶC kết quả là not_found
    _hv = st.session_state.headcode_val.strip()
    _cur_lr  = st.session_state.lookup_result
    _cur_lhc = st.session_state.lookup_headcode
    _is_not_found = _cur_lr and _cur_lr.get("status") == "not_found"
    if _hv and (_cur_lhc != _hv or not _cur_lr or _is_not_found):
        _r = lookup_in_cache(_hv)
        st.session_state.lookup_headcode = _hv
        st.session_state.lookup_result   = _r
        # Nếu vẫn not_found → xóa để lần sau thử lại
        if _r.get("status") == "not_found":
            st.session_state.lookup_result = None
            st.session_state.lookup_headcode = ""

    if st.session_state.lookup_result and st.session_state.lookup_result.get("status") == "found":
        r = st.session_state.lookup_result
        st.success(f"✅ **{st.session_state.lookup_headcode}** — {r.get('ten_san_pham','')}")
    elif st.session_state.lookup_headcode and st.session_state.lookup_result and st.session_state.lookup_result.get("status") == "not_found":
        st.info(f"ℹ️ Mã **{st.session_state.lookup_headcode}** — không tìm thấy thông tin sản phẩm, vẫn có thể tiếp tục.")
    st.markdown('</div>', unsafe_allow_html=True)

    if _is_san_xuat:
        # Form

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
                <div style="color:#94a3b8; margin-top:4px;"><b>ĐVT:</b> {r.get('dvt','')}</div>
            </div>""", unsafe_allow_html=True)

        # ── Công đoạn hiện tại — chỉ hiện đúng nhóm của user ──
        _nhom_user = st.session_state.get("current_nhom", "")
        _ds_cd     = get_congdoan_list(_nhom_user)  # Lọc theo nhóm

        # Hiển thị nhãn nhóm nếu có
        if _nhom_user:
            st.markdown(
                f'<div style="font-size:0.72rem; color:#1d4ed8; font-family:Inter,sans-serif; font-weight:600;'
                f' margin-bottom:4px;">📋 NHÓM: {_nhom_user}</div>',
                unsafe_allow_html=True
            )

        _cd_key = f"_congdoan_{st.session_state.form_key}"
        def on_congdoan_change():
            st.session_state.congdoan_val      = st.session_state[_cd_key]
            st.session_state.congdoan_tiep_val = ""
        # Nếu congdoan_val rỗng hoặc không thuộc nhóm → tự động set về đầu danh sách
        if not st.session_state.congdoan_val or st.session_state.congdoan_val not in _ds_cd:
            st.session_state.congdoan_val = _ds_cd[0] if _ds_cd else ""
        _cd_idx = _ds_cd.index(st.session_state.congdoan_val)               if st.session_state.congdoan_val in _ds_cd else 0
        st.selectbox("Công đoạn hiện tại *", options=_ds_cd,
            index=_cd_idx, key=_cd_key, on_change=on_congdoan_change)

        # ── Công đoạn tiếp theo — lọc theo nhóm user ──
        # Nhóm 1 (CTS/TỔ ĐÁ/ĐÓNG KIỆN): chỉ thấy công đoạn thuộc 3 nhóm này
        # Nhóm 2 (TỔ KÍNH): chỉ thấy công đoạn thuộc TỔ KÍNH
        # Không có nhóm: thấy tất cả
        _NHOM_1 = {"CTS", "TỔ ĐÁ", "ĐÓNG KIỆN"}
        _NHOM_2 = {"TỔ KÍNH"}
        _nhom_u = st.session_state.get("current_nhom", "").strip()
        _full_list = st.session_state.congdoan_list or DANH_SACH_CONG_DOAN_DEFAULT

        if _nhom_u in _NHOM_1:
            _ds_tiep = [item["ten"] for item in _full_list
                        if item.get("nhom","").strip() in _NHOM_1]
        elif _nhom_u in _NHOM_2:
            _ds_tiep = [item["ten"] for item in _full_list
                        if item.get("nhom","").strip() in _NHOM_2]
        else:
            _ds_tiep = [item["ten"] for item in _full_list]

        _cd_tiep_opts = ["-- Chọn công đoạn tiếp theo --"] + [
            cd for cd in _ds_tiep if cd != st.session_state.congdoan_val
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
            pass
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

            # Upload ảnh — chỉ hiển thị khi chế độ HOÀN THÀNH
            uploaded_img = None
            if is_active_live:
                st.markdown("📷 **Hình ảnh hoàn thành** *(bắt buộc)*")
                uploaded_img = st.file_uploader(
                    "Chọn hoặc chụp ảnh",
                    type=["jpg","jpeg","png","webp"],
                    accept_multiple_files=False,
                    key=f"img_upload_{st.session_state.form_key}",
                    label_visibility="collapsed"
                )
                if uploaded_img:
                    st.image(uploaded_img, caption="Xem trước ảnh", width=200)

            submit = st.form_submit_button(
                label=f"💾 XÁC NHẬN — {mode_label}", use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True)

        # Dọn dẹp memory định kỳ
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
                # Headcode không có trong DATA → vẫn cho phép, coi như found với thông tin trống
                st.session_state.lookup_result = {
                    "status": "found",
                    "ten_cong_trinh": "",
                    "ten_san_pham": "",
                    "dvt": ""
                }
            else:
                congdoan_tiep = st.session_state.congdoan_tiep_val.strip()
                job_key   = f"{headcode}|{congdoan}|{nguoibao.lower()}"
                is_active = job_key in st.session_state.active_jobs

                # Bắt buộc chọn công đoạn tiếp theo khi HOÀN THÀNH
                if is_active and not congdoan_tiep:
                    st.error("❌ Vui lòng chọn Công đoạn tiếp theo trước khi hoàn thành.")
                elif is_active and uploaded_img is None:
                    st.error("❌ Vui lòng chụp hoặc chọn Hình ảnh trước khi hoàn thành.")
                elif not is_active:
                    _lr = st.session_state.lookup_result or {}
                    payload = {
                        "action":          "start",
                        "headcode":        headcode,
                        "ten_cong_trinh":  _lr.get("ten_cong_trinh", ""),
                        "ten_san_pham":    _lr.get("ten_san_pham", ""),
                        "dvt":             _lr.get("dvt", ""),
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
                        st.warning("⚠️ Mã đã được ghi nhận.")
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

                        # Upload ảnh nếu người dùng đã chọn
                        if uploaded_img is not None:
                            raw_bytes = uploaded_img.getvalue()
                            # Nén ảnh xuống dưới 900KB trước khi upload
                            with st.spinner("🗜️ Đang nén ảnh..."):
                                img_bytes, mime = compress_image(raw_bytes, max_kb=900)
                            orig_kb = len(raw_bytes) / 1024
                            comp_kb = len(img_bytes) / 1024
                            if orig_kb > comp_kb + 10:
                                st.caption(f"📉 Đã nén: {orig_kb:.0f}KB → {comp_kb:.0f}KB")
                            fname     = f"{headcode}_{congdoan}_{nguoibao}.jpg".replace(" ","_")
                            with st.spinner("📤 Đang upload hình ảnh..."):
                                img_result = upload_image_to_sheet(
                                    job_info.get("row_id",""), headcode, congdoan,
                                    nguoibao, img_bytes, mime, fname)
                            if img_result.get("status") == "ok":
                                st.success("🖼️ Đã ghi hình ảnh vào Sheet!")
                            else:
                                st.warning(f"⚠️ Upload ảnh thất bại: {img_result.get('message','')}")

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
    _is_sx_right = normalize_role(st.session_state.current_role) == "sanxuat"

    if _is_sx_right:
        if st.session_state.last_action:
            act = st.session_state.last_action
            if act["type"] == "start":
                st.success(f"🚀 ĐÃ BẮT ĐẦU: **{act['headcode']}** — {act['congdoan']}")
            else:
                st.success(f"🏁 ĐÃ HOÀN THÀNH: **{act['headcode']}** — {act['congdoan']}")
    
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🔄 Làm mới danh sách", use_container_width=True):
                with st.spinner("Đang tải..."):
                    st.session_state.active_jobs = fetch_active_jobs_from_sheet()
                st.rerun()
        with col_r2:
            if st.button("🗄️ Làm mới dữ liệu DATA", use_container_width=True):
                st.session_state.cache_version      = st.session_state.get("cache_version", 0) + 1
                st.session_state.congdoan_list      = []
                st.session_state.active_jobs_loaded = False
                st.session_state.lookup_headcode    = ""
                st.session_state.lookup_result      = None
                st.session_state.congdoan_val       = ""
                st.rerun()


    
        init_info = fetch_init_data(st.session_state.get("cache_version", 0))
        loaded_at = init_info["loaded_at"] if init_info else None
        if loaded_at:
            st.markdown(f'<div style="font-size:0.72rem; color:#64748b; text-align:center; margin-bottom:8px;">'
                        f'🗄️ DATA: <b style="color:#94a3b8">{loaded_at}</b> | Tự làm mới sau 24h</div>',
                        unsafe_allow_html=True)
    
        # Danh sách đang xử lý
        # Người xem đã có bảng bên trái — chỉ hiện job cards cho SẢN XUẤT
            st.markdown('<div class="card"><div class="card-title">⚡ Đang xử lý</div>', unsafe_allow_html=True)
        active_jobs    = st.session_state.active_jobs
        _login_ten     = st.session_state.current_ten.strip().lower()
        _is_viewer     = normalize_role(st.session_state.current_role) != "sanxuat"
        # Lọc: người xem thấy tất cả, người sản xuất chỉ thấy của mình
        if _is_viewer:
            filtered_jobs = active_jobs
        else:
            filtered_jobs = {
                jk: job for jk, job in active_jobs.items()
                if job.get("nguoibao", "").strip().lower() == _login_ten
            }
        if not filtered_jobs:
            st.markdown('<p style="color:#64748b; font-size:0.85rem; font-family:IBM Plex Mono,monospace;">— Chưa có công việc nào —</p>', unsafe_allow_html=True)
        else:
            for jk, job in list(filtered_jobs.items()):
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
                <div style="font-family:IBM Plex Mono,monospace;color:#d97706;font-weight:600;">{row.get('headcode','')}</div>
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
