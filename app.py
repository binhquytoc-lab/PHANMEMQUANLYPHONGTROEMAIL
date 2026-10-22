
import os
import sqlite3
import smtplib
from email.message import EmailMessage
from contextlib import closing
from datetime import datetime

import pandas as pd
import streamlit as st
from fpdf import FPDF

# ======================================
# CẤU HÌNH CHUNG
# ======================================
DB_PATH = "tien_tro.db"
TEN_DAY_TRO = "DÃY TRỌ VŨ ĐỨC BÌNH"
TRANG_THAI = ["Chưa thanh toán", "Đã thanh toán"]
GIA_PHONG_MAC_DINH = 4_000_000

CAI_DAT_MAC_DINH = {
    "gia_dien": 3000,
    "gia_nuoc": 15000,
    "phi_khac": 100000,
    "so_phong": 50,
}

st.set_page_config(
    page_title="Quản lý tiền phòng trọ",
    page_icon="🏠",
    layout="wide",
)


# ======================================
# DATABASE (SQLITE)
# ======================================
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS month_prices (
                nam INTEGER NOT NULL,
                thang INTEGER NOT NULL,
                gia_dien INTEGER NOT NULL,
                gia_nuoc INTEGER NOT NULL,
                phi_khac INTEGER NOT NULL,
                PRIMARY KEY (nam, thang)
            );

            CREATE TABLE IF NOT EXISTS records (
                nam INTEGER NOT NULL,
                thang INTEGER NOT NULL,
                phong INTEGER NOT NULL,
                gia_phong INTEGER NOT NULL DEFAULT 0,
                nguoi_o TEXT NOT NULL DEFAULT '',
                sdt TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                so_nguoi INTEGER NOT NULL DEFAULT 1,
                dien_cu INTEGER NOT NULL DEFAULT 0,
                dien_moi INTEGER NOT NULL DEFAULT 0,
                nuoc_cu INTEGER NOT NULL DEFAULT 0,
                nuoc_moi INTEGER NOT NULL DEFAULT 0,
                trang_thai TEXT NOT NULL DEFAULT 'Chưa thanh toán',
                PRIMARY KEY (nam, thang, phong)
            );
            """
        )

        # Nâng cấp database cũ nếu chưa có cột email.
        columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(records)"
            ).fetchall()
        ]

        if "email" not in columns:
            conn.execute(
                "ALTER TABLE records "
                "ADD COLUMN email TEXT NOT NULL DEFAULT ''"
            )

        conn.commit()


def get_setting(key):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()

    return int(row["value"]) if row else CAI_DAT_MAC_DINH[key]


def set_setting(key, value):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (key, int(value)),
        )
        conn.commit()


def get_month_prices(nam, thang):
    """
    Đơn giá riêng của từng tháng.
    Tháng mới kế thừa đơn giá gần nhất của tháng trước.
    """
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT gia_dien, gia_nuoc, phi_khac
            FROM month_prices
            WHERE nam = ? AND thang = ?
            """,
            (nam, thang),
        ).fetchone()

        if row:
            return dict(row)

        row = conn.execute(
            """
            SELECT gia_dien, gia_nuoc, phi_khac
            FROM month_prices
            WHERE (nam * 100 + thang) < ?
            ORDER BY (nam * 100 + thang) DESC
            LIMIT 1
            """,
            (nam * 100 + thang,),
        ).fetchone()

        prices = (
            dict(row)
            if row
            else {
                k: CAI_DAT_MAC_DINH[k]
                for k in ("gia_dien", "gia_nuoc", "phi_khac")
            }
        )

        conn.execute(
            """
            INSERT INTO month_prices
            (nam, thang, gia_dien, gia_nuoc, phi_khac)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                nam,
                thang,
                prices["gia_dien"],
                prices["gia_nuoc"],
                prices["phi_khac"],
            ),
        )
        conn.commit()

    return prices


def save_month_prices(nam, thang, gia_dien, gia_nuoc, phi_khac):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE month_prices
            SET gia_dien = ?, gia_nuoc = ?, phi_khac = ?
            WHERE nam = ? AND thang = ?
            """,
            (gia_dien, gia_nuoc, phi_khac, nam, thang),
        )
        conn.commit()


# ======================================
# TẠO DỮ LIỆU CÁC PHÒNG THEO THÁNG
# ======================================
def ensure_records(nam, thang, so_phong):
    """
    Tạo dữ liệu cho phòng chưa tồn tại trong tháng.

    Thông tin kế thừa từ tháng gần nhất trước đó:
    - Giá phòng
    - Họ tên người ở
    - Số điện thoại
    - Email

    Chỉ số điện nước đầu kỳ lấy từ chỉ số cuối kỳ trước đó.
    """
    with closing(get_conn()) as conn:
        for phong in range(1, so_phong + 1):

            exists = conn.execute(
                """
                SELECT 1 FROM records
                WHERE nam = ? AND thang = ? AND phong = ?
                """,
                (nam, thang, phong),
            ).fetchone()

            if exists:
                continue

            prev = conn.execute(
                """
                SELECT *
                FROM records
                WHERE phong = ?
                  AND (nam * 100 + thang) < ?
                ORDER BY (nam * 100 + thang) DESC
                LIMIT 1
                """,
                (phong, nam * 100 + thang),
            ).fetchone()

            if prev:
                values = (
                    nam,
                    thang,
                    phong,
                    prev["gia_phong"],
                    prev["nguoi_o"],
                    prev["sdt"],
                    prev["email"],
                    prev["so_nguoi"],
                    prev["dien_moi"],
                    prev["dien_moi"],
                    prev["nuoc_moi"],
                    prev["nuoc_moi"],
                    TRANG_THAI[0],
                )
            else:
                values = (
                    nam,
                    thang,
                    phong,
                    GIA_PHONG_MAC_DINH,
                    "",
                    "",
                    "",
                    1,
                    0,
                    0,
                    0,
                    0,
                    TRANG_THAI[0],
                )

            conn.execute(
                """
                INSERT INTO records (
                    nam, thang, phong, gia_phong,
                    nguoi_o, sdt, email, so_nguoi,
                    dien_cu, dien_moi,
                    nuoc_cu, nuoc_moi, trang_thai
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

        conn.commit()


def get_record(nam, thang, phong):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT * FROM records
            WHERE nam = ? AND thang = ? AND phong = ?
            """,
            (nam, thang, phong),
        ).fetchone()

    return dict(row)


def get_records(nam, thang, so_phong):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM records
            WHERE nam = ? AND thang = ? AND phong <= ?
            ORDER BY phong
            """,
            (nam, thang, so_phong),
        ).fetchall()

    return [dict(r) for r in rows]


# ======================================
# LƯU THÔNG TIN PHÒNG
# ======================================
def save_record(nam, thang, phong, d):
    """
    Lưu thông tin phòng của tháng đang chọn.

    TỰ ĐỘNG ĐỒNG BỘ SANG CÁC THÁNG SAU:
    - Giá phòng
    - Họ tên người ở
    - Số điện thoại
    - Email

    Các dữ liệu khác của những tháng sau không bị ghi đè.
    Chỉ số điện, nước đầu kỳ của tháng kế tiếp vẫn được
    cập nhật theo chỉ số cuối kỳ của tháng hiện tại.
    """
    with closing(get_conn()) as conn:

        # 1. Lưu thông tin tháng đang chọn.
        conn.execute(
            """
            UPDATE records
            SET gia_phong = ?,
                nguoi_o = ?,
                sdt = ?,
                email = ?,
                dien_cu = ?,
                dien_moi = ?,
                nuoc_cu = ?,
                nuoc_moi = ?,
                trang_thai = ?
            WHERE nam = ? AND thang = ? AND phong = ?
            """,
            (
                d["gia_phong"],
                d["nguoi_o"],
                d["sdt"],
                d["email"],
                d["dien_cu"],
                d["dien_moi"],
                d["nuoc_cu"],
                d["nuoc_moi"],
                d["trang_thai"],
                nam,
                thang,
                phong,
            ),
        )

        # 2. Đồng bộ 4 thông tin sang tất cả các tháng sau
        # đã tồn tại trong database.
        #
        # Không cập nhật chỉ số điện nước, số người,
        # trạng thái thanh toán hoặc các dữ liệu khác.
        conn.execute(
            """
            UPDATE records
            SET gia_phong = ?,
                nguoi_o = ?,
                sdt = ?,
                email = ?
            WHERE phong = ?
              AND (nam * 100 + thang) > ?
            """,
            (
                d["gia_phong"],
                d["nguoi_o"],
                d["sdt"],
                d["email"],
                phong,
                nam * 100 + thang,
            ),
        )

        # 3. Cập nhật chỉ số đầu kỳ của tháng kế tiếp
        # nếu tháng kế tiếp đã có dữ liệu.
        if thang == 12:
            nam_sau, thang_sau = nam + 1, 1
        else:
            nam_sau, thang_sau = nam, thang + 1

        conn.execute(
            """
            UPDATE records
            SET dien_cu = ?, nuoc_cu = ?
            WHERE nam = ? AND thang = ? AND phong = ?
            """,
            (
                d["dien_moi"],
                d["nuoc_moi"],
                nam_sau,
                thang_sau,
                phong,
            ),
        )

        conn.commit()


# ======================================
# TÍNH TOÁN
# ======================================
def tinh_tien(rec, prices):
    so_dien = max(rec["dien_moi"] - rec["dien_cu"], 0)
    so_nuoc = max(rec["nuoc_moi"] - rec["nuoc_cu"], 0)

    tien_dien = so_dien * prices["gia_dien"]
    tien_nuoc = so_nuoc * prices["gia_nuoc"]

    tong = (
        rec["gia_phong"]
        + tien_dien
        + tien_nuoc
        + prices["phi_khac"]
    )

    return {
        "so_dien": so_dien,
        "so_nuoc": so_nuoc,
        "tien_dien": tien_dien,
        "tien_nuoc": tien_nuoc,
        "phi_khac": prices["phi_khac"],
        "tong": tong,
    }


def tien(x):
    return f"{int(x):,}".replace(",", ".")


# ======================================
# XUẤT PDF
# ======================================
FONT_REGULAR = [
    "fonts/DejaVuSans.ttf",
    "fonts/Roboto-Regular.ttf",
    "fonts/NotoSans-Regular.ttf",
    "fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

FONT_BOLD = [
    "fonts/DejaVuSans-Bold.ttf",
    "fonts/Roboto-Bold.ttf",
    "fonts/NotoSans-Bold.ttf",
    "fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def tim_font(danh_sach):
    for path in danh_sach:
        if os.path.exists(path):
            return path
    return None


def tao_pdf(nam, thang, danh_sach):
    """Mỗi phòng một trang PDF khổ A5."""
    reg = tim_font(FONT_REGULAR)

    if not reg:
        raise FileNotFoundError(
            "Không tìm thấy font hỗ trợ tiếng Việt. "
            "Hãy copy file DejaVuSans.ttf và DejaVuSans-Bold.ttf "
            "vào thư mục 'fonts' cạnh file app.py."
        )

    bold = tim_font(FONT_BOLD) or reg

    pdf = FPDF(orientation="P", unit="mm", format="A5")
    pdf.set_auto_page_break(auto=False)
    pdf.add_font("VN", "", reg)
    pdf.add_font("VN", "B", bold)

    w = [30, 64, 34]

    for rec, kq, prices in danh_sach:
        pdf.add_page()
        pdf.set_margins(10, 10, 10)
        pdf.set_xy(10, 12)

        pdf.set_font("VN", "B", 13)
        pdf.cell(
            0, 7, TEN_DAY_TRO,
            align="C", new_x="LMARGIN", new_y="NEXT"
        )

        pdf.set_font("VN", "B", 16)
        pdf.cell(
            0, 9, "PHIẾU THU TIỀN PHÒNG",
            align="C", new_x="LMARGIN", new_y="NEXT"
        )

        pdf.set_font("VN", "", 10)
        pdf.cell(
            0, 6, f"Tháng {thang}/{nam}",
            align="C", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(4)

        thong_tin = [
            ("Phòng:", str(rec["phong"])),
            ("Người ở:", rec["nguoi_o"] or "-"),
            ("Điện thoại:", rec["sdt"] or "-"),
            ("Email:", rec.get("email", "") or "-"),
        ]

        for nhan, gia_tri in thong_tin:
            pdf.set_font("VN", "B", 10)
            pdf.cell(30, 6, nhan)
            pdf.set_font("VN", "", 10)
            pdf.cell(
                0, 6, gia_tri,
                new_x="LMARGIN", new_y="NEXT"
            )

        pdf.ln(3)

        pdf.set_font("VN", "B", 10)
        pdf.set_fill_color(230, 230, 230)

        pdf.cell(w[0], 8, "Khoản mục", border=1, align="C", fill=True)
        pdf.cell(w[1], 8, "Chi tiết", border=1, align="C", fill=True)
        pdf.cell(
            w[2], 8, "Thành tiền (đ)",
            border=1, align="C", fill=True,
            new_x="LMARGIN", new_y="NEXT"
        )

        dong = [
            ("Tiền phòng", "", rec["gia_phong"]),
            (
                "Tiền điện",
                f"{rec['dien_cu']} → {rec['dien_moi']} = "
                f"{kq['so_dien']} kWh x {tien(prices['gia_dien'])}",
                kq["tien_dien"],
            ),
            (
                "Tiền nước",
                f"{rec['nuoc_cu']} → {rec['nuoc_moi']} = "
                f"{kq['so_nuoc']} m³ x {tien(prices['gia_nuoc'])}",
                kq["tien_nuoc"],
            ),
            ("Phí khác", "Wifi, vệ sinh...", kq["phi_khac"]),
        ]

        pdf.set_font("VN", "", 9)

        for ten_khoan, chi_tiet, so_tien in dong:
            pdf.cell(w[0], 8, ten_khoan, border=1)
            pdf.cell(w[1], 8, chi_tiet, border=1)
            pdf.cell(
                w[2], 8, tien(so_tien),
                border=1, align="R",
                new_x="LMARGIN", new_y="NEXT"
            )

        pdf.set_font("VN", "B", 11)
        pdf.cell(
            w[0] + w[1], 9, "TỔNG CỘNG",
            border=1, align="C"
        )
        pdf.cell(
            w[2], 9, tien(kq["tong"]),
            border=1, align="R",
            new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(4)

        pdf.set_font("VN", "B", 10)
        pdf.cell(35, 6, "Trạng thái:")
        pdf.set_font("VN", "", 10)
        pdf.cell(
            0, 6, rec["trang_thai"],
            new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(4)

        pdf.set_font("VN", "", 9)
        pdf.cell(
            0, 5,
            f"Ngày lập: {datetime.now().strftime('%d/%m/%Y')}",
            align="R", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(3)

        pdf.set_font("VN", "B", 10)
        pdf.cell(64, 6, "Chủ trọ", align="C")
        pdf.cell(
            64, 6, "Người thuê",
            align="C", new_x="LMARGIN", new_y="NEXT"
        )

        pdf.set_font("VN", "", 8)
        pdf.cell(64, 5, "(Ký, ghi rõ họ tên)", align="C")
        pdf.cell(
            64, 5, "(Ký, ghi rõ họ tên)",
            align="C", new_x="LMARGIN", new_y="NEXT"
        )

    return bytes(pdf.output())


# ======================================
# GỬI EMAIL KÈM PHIẾU THU PDF
# ======================================
def gui_email_hoa_don(
    email_nhan, nam, thang, phong, rec, kq, prices, pdf_bytes
):
    """Gửi PDF qua Gmail SMTP SSL, sử dụng thông tin st.secrets."""

    if not email_nhan or "@" not in email_nhan:
        raise ValueError(
            "Vui lòng nhập email người thuê hợp lệ và lưu thông tin phòng trước."
        )

    try:
        gmail_cfg = st.secrets["gmail"]
        email_gui = str(gmail_cfg["address"]).strip()
        app_password = (
            str(gmail_cfg["app_password"]).replace(" ", "").strip()
        )
    except Exception as exc:
        raise RuntimeError(
            "Chưa cấu hình Secrets. Hãy thêm [gmail] với address "
            "và app_password trong Settings → Secrets."
        ) from exc

    if not email_gui or not app_password:
        raise RuntimeError(
            "Secrets [gmail] đang thiếu address hoặc app_password."
        )

    msg = EmailMessage()
    msg["Subject"] = (
        f"Phiếu thu tiền phòng {phong} - Tháng {thang}/{nam}"
    )
    msg["From"] = email_gui
    msg["To"] = email_nhan

    ten = rec.get("nguoi_o", "").strip() or "Quý khách"

    msg.set_content(
        f"Kính gửi {ten},\n\n"
        f"Dãy trọ {TEN_DAY_TRO} gửi Quý khách phiếu thu "
        f"tiền phòng tháng {thang}/{nam}.\n"
        f"Phòng: {phong}\n"
        f"Tổng tiền: {tien(kq['tong'])} VNĐ\n"
        f"Trạng thái thanh toán: {rec['trang_thai']}\n\n"
        "Vui lòng xem chi tiết trong file PDF đính kèm. "
        "Nếu đã thanh toán, Quý khách có thể bỏ qua thông báo này.\n\n"
        f"Trân trọng,\n{TEN_DAY_TRO}"
    )

    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"Phieu_Phong_{phong}_{thang:02d}_{nam}.pdf",
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, timeout=30
    ) as server:
        server.login(email_gui, app_password)
        server.send_message(msg)


# ======================================
# GIAO DIỆN STREAMLIT
# ======================================
init_db()

st.title(f"PHẦN MỀM QUẢN LÝ THU TIỀN {TEN_DAY_TRO}")


# ======================================
# SIDEBAR - CẤU HÌNH
# ======================================
st.sidebar.header("Cấu hình")

so_phong = st.sidebar.slider(
    "Số lượng phòng",
    min_value=1,
    max_value=100,
    value=get_setting("so_phong"),
    step=1,
)

if so_phong != get_setting("so_phong"):
    set_setting("so_phong", so_phong)

col_nam, col_thang = st.sidebar.columns(2)

with col_nam:
    nam_hien_tai = datetime.now().year
    danh_sach_nam = list(
        range(nam_hien_tai - 1, nam_hien_tai + 6)
    )

    nam_chon = st.selectbox(
        "Chọn năm:",
        danh_sach_nam,
        index=danh_sach_nam.index(nam_hien_tai),
    )

with col_thang:
    idx_thang_chon = st.selectbox(
        "Chọn tháng:",
        list(range(1, 13)),
        index=datetime.now().month - 1,
        format_func=lambda x: f"Tháng {x}",
    )

thang_chon = f"Tháng {idx_thang_chon}/{nam_chon}"


# ======================================
# ĐƠN GIÁ ĐIỆN NƯỚC
# ======================================
st.sidebar.header("Đơn giá điện nước")
st.sidebar.caption(f"Đơn giá áp dụng riêng cho {thang_chon}")

prices_db = get_month_prices(nam_chon, idx_thang_chon)
suffix = f"{nam_chon}_{idx_thang_chon}"

gia_dien = st.sidebar.number_input(
    "Giá điện (đ/kWh)",
    min_value=0,
    value=int(prices_db["gia_dien"]),
    step=100,
    key=f"gia_dien_{suffix}",
)

gia_nuoc = st.sidebar.number_input(
    "Giá nước (đ/m³)",
    min_value=0,
    value=int(prices_db["gia_nuoc"]),
    step=500,
    key=f"gia_nuoc_{suffix}",
)

phi_khac = st.sidebar.number_input(
    "Phí khác (wifi, vệ sinh...)",
    min_value=0,
    value=int(prices_db["phi_khac"]),
    step=10000,
    key=f"phi_khac_{suffix}",
)

prices = {
    "gia_dien": gia_dien,
    "gia_nuoc": gia_nuoc,
    "phi_khac": phi_khac,
}

if prices != prices_db:
    save_month_prices(
        nam_chon,
        idx_thang_chon,
        gia_dien,
        gia_nuoc,
        phi_khac,
    )


# ======================================
# ĐẢM BẢO DỮ LIỆU PHÒNG TỒN TẠI
# ======================================
ensure_records(nam_chon, idx_thang_chon, so_phong)


# ======================================
# NHẬP VÀ CẬP NHẬT DỮ LIỆU PHÒNG
# ======================================
st.header(f"Nhập số liệu - {thang_chon}")

phong = st.selectbox(
    "Chọn phòng cần nhập dữ liệu:",
    range(1, so_phong + 1),
    key=f"selectbox_phong_{suffix}",
)

rec = get_record(nam_chon, idx_thang_chon, phong)

st.subheader(f"Cập nhật: Phòng {phong} ({thang_chon})")

with st.form(key=f"form_{suffix}_{phong}"):

    # Hàng 1: Giá phòng và thông tin người ở
    a1, a2, a3, a4 = st.columns([1.2, 1.5, 1.2, 1.6])

    with a1:
        gia_phong = st.number_input(
            "Giá phòng (VNĐ)",
            min_value=0,
            value=int(rec["gia_phong"]),
            step=50000,
        )

    with a2:
        nguoi_o = st.text_input(
            "Họ tên người ở",
            value=rec["nguoi_o"],
        )

    with a3:
        sdt = st.text_input(
            "Số điện thoại",
            value=rec["sdt"],
        )

    with a4:
        email = st.text_input(
            "Địa chỉ email người thuê",
            value=rec.get("email", ""),
            placeholder="khachhang@gmail.com",
        )

    # Hàng 2: Chỉ số điện nước
    b1, b2, b3, b4 = st.columns(4)

    with b1:
        dien_cu = st.number_input(
            "Số điện CŨ",
            min_value=0,
            value=int(rec["dien_cu"]),
        )

    with b2:
        dien_moi = st.number_input(
            "Số điện MỚI",
            min_value=0,
            value=int(rec["dien_moi"]),
        )

    with b3:
        nuoc_cu = st.number_input(
            "Số nước CŨ",
            min_value=0,
            value=int(rec["nuoc_cu"]),
        )

    with b4:
        nuoc_moi = st.number_input(
            "Số nước MỚI",
            min_value=0,
            value=int(rec["nuoc_moi"]),
        )

    # Hàng 3: Trạng thái thanh toán
    trang_thai = st.radio(
        "Trạng thái thanh toán",
        TRANG_THAI,
        index=(
            TRANG_THAI.index(rec["trang_thai"])
            if rec["trang_thai"] in TRANG_THAI
            else 0
        ),
        horizontal=True,
    )

    submitted = st.form_submit_button(
        "Lưu thông tin phòng",
        type="primary",
    )


if submitted:
    save_record(
        nam_chon,
        idx_thang_chon,
        phong,
        {
            "gia_phong": gia_phong,
            "nguoi_o": nguoi_o.strip(),
            "sdt": sdt.strip(),
            "email": email.strip(),
            "dien_cu": dien_cu,
            "dien_moi": dien_moi,
            "nuoc_cu": nuoc_cu,
            "nuoc_moi": nuoc_moi,
            "trang_thai": trang_thai,
        },
    )

    st.success(
        f"Đã lưu Phòng {phong} - {thang_chon}. "
        "Thông tin giá phòng, họ tên, số điện thoại và email "
        "đã được đồng bộ sang các tháng sau."
    )

    # Đọc lại dữ liệu sau khi lưu.
    rec = get_record(nam_chon, idx_thang_chon, phong)


# ======================================
# XUẤT PDF PHÒNG ĐANG CHỌN
# ======================================
try:
    pdf_phong = tao_pdf(
        nam_chon,
        idx_thang_chon,
        [(rec, tinh_tien(rec, prices), prices)],
    )

    st.download_button(
        label=f"Xuất PDF Phòng {phong} - {thang_chon}",
        data=pdf_phong,
        file_name=(
            f"Phieu_Phong_{phong}_"
            f"{idx_thang_chon:02d}_{nam_chon}.pdf"
        ),
        mime="application/pdf",
        key=f"pdf_phong_{suffix}_{phong}",
    )

except FileNotFoundError as e:
    st.warning(str(e))


# ======================================
# GỬI EMAIL CHO PHÒNG ĐANG CHỌN
# ======================================
st.divider()
st.subheader(f"📧 Gửi phiếu thu qua email - Phòng {phong}")

email_hien_tai = rec.get("email", "")

if not email_hien_tai:
    st.warning(
        "Phòng này chưa có địa chỉ email. "
        "Nhập email ở phần cập nhật và bấm Lưu thông tin phòng "
        "trước khi gửi."
    )
else:
    st.caption(f"Email người nhận: {email_hien_tai}")
    st.caption(
        "Email sẽ đính kèm phiếu thu PDF của phòng đang chọn, "
        "đúng tháng/năm hiện tại."
    )

if st.button(
    f"📨 Gửi email hóa đơn Phòng {phong}",
    type="primary",
    key=f"send_email_{suffix}_{phong}",
):
    if not email_hien_tai:
        st.error(
            "Chưa có email người nhận. "
            "Vui lòng nhập email và lưu thông tin phòng trước."
        )
    else:
        try:
            pdf_gui = tao_pdf(
                nam_chon,
                idx_thang_chon,
                [(rec, tinh_tien(rec, prices), prices)],
            )

            gui_email_hoa_don(
                email_hien_tai,
                nam_chon,
                idx_thang_chon,
                phong,
                rec,
                tinh_tien(rec, prices),
                prices,
                pdf_gui,
            )

            st.success(
                f"Đã gửi email hóa đơn Phòng {phong} "
                f"đến {email_hien_tai}."
            )

        except Exception as e:
            st.error(f"Gửi email chưa thành công: {e}")
            st.info(
                "Kiểm tra Secrets, địa chỉ email nhận và Gmail "
                "App Password 16 ký tự. Không dùng mật khẩu "
                "đăng nhập Gmail thông thường."
            )


# ======================================
# BẢNG TỔNG HỢP
# ======================================
st.divider()
st.header(f"Bảng tổng hợp tiền trọ - {thang_chon}")

records = get_records(nam_chon, idx_thang_chon, so_phong)

ket_qua = []
tong_doanh_thu = 0
da_thu = 0
danh_sach_pdf = []

for r in records:
    kq = tinh_tien(r, prices)

    tong_doanh_thu += kq["tong"]

    if r["trang_thai"] == TRANG_THAI[1]:
        da_thu += kq["tong"]

    danh_sach_pdf.append((r, kq, prices))

    ket_qua.append(
        {
            "Phòng": f"Phòng {r['phong']}",
            "Người ở": r["nguoi_o"],
            "SĐT": r["sdt"],
            "Email": r.get("email", ""),
            "Giá phòng": r["gia_phong"],
            "Số điện cũ": r["dien_cu"],
            "Số điện mới": r["dien_moi"],
            "Tiền điện": kq["tien_dien"],
            "Số nước cũ": r["nuoc_cu"],
            "Số nước mới": r["nuoc_moi"],
            "Tiền nước": kq["tien_nuoc"],
            "Phí khác": kq["phi_khac"],
            "Tổng tiền": kq["tong"],
            "Thanh toán": r["trang_thai"],
        }
    )


if ket_qua:
    df = pd.DataFrame(ket_qua)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Giá phòng": st.column_config.NumberColumn(
                format="%d"
            ),
            "Tiền điện": st.column_config.NumberColumn(
                format="%d"
            ),
            "Tiền nước": st.column_config.NumberColumn(
                format="%d"
            ),
            "Phí khác": st.column_config.NumberColumn(
                format="%d"
            ),
            "Tổng tiền": st.column_config.NumberColumn(
                format="%d"
            ),
        },
    )

    m1, m2, m3 = st.columns(3)

    m1.metric(
        f"Tổng thu nhập các phòng ({thang_chon})",
        f"{tong_doanh_thu:,.0f} VNĐ",
    )

    m2.metric(
        "Đã thu",
        f"{da_thu:,.0f} VNĐ",
    )

    m3.metric(
        "Chưa thu",
        f"{tong_doanh_thu - da_thu:,.0f} VNĐ",
    )

    # ======================================
    # XUẤT BÁO CÁO
    # ======================================
    st.subheader("Xuất báo cáo")

    e1, e2, e3 = st.columns(3)

    with e1:
        csv = df.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            label=f"Xuất bảng tổng hợp {thang_chon} (CSV)",
            data=csv,
            file_name=(
                f"Bang_Tien_Phong_"
                f"{idx_thang_chon:02d}_{nam_chon}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )

    with e2:
        try:
            pdf_all = tao_pdf(
                nam_chon,
                idx_thang_chon,
                danh_sach_pdf,
            )

            st.download_button(
                label=f"Xuất PDF tất cả phòng {thang_chon}",
                data=pdf_all,
                file_name=(
                    f"Phieu_Tat_Ca_Phong_"
                    f"{idx_thang_chon:02d}_{nam_chon}.pdf"
                ),
                mime="application/pdf",
                use_container_width=True,
            )

        except FileNotFoundError as e:
            st.warning(str(e))

    with e3:
        if os.path.exists(DB_PATH):
            with open(DB_PATH, "rb") as f:
                st.download_button(
                    label="Sao lưu database (.db)",
                    data=f.read(),
                    file_name=(
                        "tien_tro_backup_"
                        f"{datetime.now().strftime('%Y%m%d')}.db"
                    ),
                    mime="application/octet-stream",
                    use_container_width=True,
                )

else:
    st.info("Chưa có dữ liệu phòng nào cho tháng này.")

