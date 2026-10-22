import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ======================================
# CẤU HÌNH TRANG
# ======================================
st.set_page_config(
    page_title="Quản lý tiền phòng trọ",
    page_icon="🏠",
    layout="wide"
)
st.title("🏠 PHẦN MỀM QUẢN LÝ THU TIỀN DÃY TRỌ_VŨ ĐỨC BÌNH")

DB_FILE = "quan_ly_tien_tro.db"

# Tự tìm font Unicode để PDF hiển thị tiếng Việt có dấu.
PDF_FONT = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
]
for regular_path, bold_path in FONT_CANDIDATES:
    if os.path.exists(regular_path) and os.path.exists(bold_path):
        try:
            pdfmetrics.registerFont(TTFont("VietnameseFont", regular_path))
            pdfmetrics.registerFont(TTFont("VietnameseFont-Bold", bold_path))
            PDF_FONT = "VietnameseFont"
            PDF_FONT_BOLD = "VietnameseFont-Bold"
            break
        except Exception:
            pass


# ======================================
# SQLITE DATABASE
# ======================================
def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_bills (
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                room_no INTEGER NOT NULL,
                room_price INTEGER NOT NULL DEFAULT 2500000,
                tenant_name TEXT NOT NULL DEFAULT '',
                tenant_phone TEXT NOT NULL DEFAULT '',
                tenant_info TEXT NOT NULL DEFAULT '',
                electric_old INTEGER NOT NULL DEFAULT 0,
                electric_new INTEGER NOT NULL DEFAULT 0,
                water_old INTEGER NOT NULL DEFAULT 0,
                water_new INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT 'Chưa thanh toán',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (year, month, room_no)
            )
        """)
        conn.commit()


def load_bill(year, month, room_no):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM room_bills
            WHERE year = ? AND month = ? AND room_no = ?
        """, (year, month, room_no)).fetchone()
    if row:
        return dict(row)
    return None


def save_bill(year, month, room_no, data):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO room_bills (
                year, month, room_no, room_price, tenant_name, tenant_phone,
                tenant_info, electric_old, electric_new, water_old, water_new,
                note, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, month, room_no) DO UPDATE SET
                room_price=excluded.room_price,
                tenant_name=excluded.tenant_name,
                tenant_phone=excluded.tenant_phone,
                tenant_info=excluded.tenant_info,
                electric_old=excluded.electric_old,
                electric_new=excluded.electric_new,
                water_old=excluded.water_old,
                water_new=excluded.water_new,
                note=excluded.note,
                updated_at=excluded.updated_at
        """, (
            year, month, room_no, data["gia_phong"], data["ten_nguoi_o"],
            data["so_dien_thoai"], data["thong_tin_nguoi_o"],
            data["dien_cu"], data["dien_moi"], data["nuoc_cu"],
            data["nuoc_moi"], data["ghi_chu"], datetime.now().isoformat(timespec="seconds")
        ))
        conn.commit()


def get_previous_readings(year, month, room_no):
    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year
    prev = load_bill(prev_year, prev_month, room_no)
    if prev:
        return int(prev["electric_new"]), int(prev["water_new"])
    return 0, 0


def money(value):
    return f"{int(value):,}".replace(",", ".") + " VNĐ"


def safe_filename(text):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


def create_invoice_pdf(year, month, room_no, data, rates):
    electric_rate, water_rate, other_fee = rates
    electric_used = max(int(data["dien_moi"]) - int(data["dien_cu"]), 0)
    water_used = max(int(data["nuoc_moi"]) - int(data["nuoc_cu"]), 0)
    electric_cost = electric_used * electric_rate
    water_cost = water_used * water_rate
    total = int(data["gia_phong"]) + electric_cost + water_cost + other_fee

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Title"], alignment=TA_CENTER,
        fontName=PDF_FONT_BOLD, fontSize=16, leading=21, spaceAfter=8
    )
    center_style = ParagraphStyle(
        "CenterSmall", parent=styles["Normal"], alignment=TA_CENTER,
        fontSize=10, leading=14
    )
    normal = ParagraphStyle(
        "VietnameseText", parent=styles["Normal"],
        fontName=PDF_FONT, fontSize=10, leading=14
    )
    story = [
        Paragraph("PHIẾU THU TIỀN PHÒNG TRỌ", title_style),
        Paragraph(f"Phòng {room_no} — Tháng {month}/{year}", center_style),
        Spacer(1, 8 * mm),
        Paragraph("<b>THÔNG TIN NGƯỜI Ở</b>", styles["Heading2"]),
    ]

    tenant_name = escape(str(data.get("ten_nguoi_o", "") or "Chưa cập nhật"))
    phone = escape(str(data.get("so_dien_thoai", "") or "Chưa cập nhật"))
    tenant_info = escape(str(data.get("thong_tin_nguoi_o", "") or ""))
    story.append(Paragraph(f"Họ tên: {tenant_name}", normal))
    story.append(Paragraph(f"Số điện thoại: {phone}", normal))
    if tenant_info:
        story.append(Paragraph(f"Thông tin thêm: {tenant_info}", normal))
    story += [Spacer(1, 5 * mm), Paragraph("<b>CHI TIẾT CÁC KHOẢN THU</b>", styles["Heading2"])]

    rows = [
        ["Khoản thu", "Số lượng / chỉ số", "Đơn giá (VNĐ)", "Thành tiền (VNĐ)"],
        ["Tiền phòng", "1 tháng", money(data["gia_phong"]), money(data["gia_phong"])],
        ["Tiền điện", f'{data["dien_cu"]} → {data["dien_moi"]} ({electric_used} kWh)',
         f"{electric_rate:,}".replace(",", "."), money(electric_cost)],
        ["Tiền nước", f'{data["nuoc_cu"]} → {data["nuoc_moi"]} ({water_used} m³)',
         f"{water_rate:,}".replace(",", "."), money(water_cost)],
        ["Phí khác (wifi, vệ sinh...)", "1 tháng", money(other_fee), money(other_fee)],
        ["TỔNG CỘNG", "", "", money(total)],
    ]
    table = Table(rows, colWidths=[43 * mm, 53 * mm, 37 * mm, 41 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF2F8")),
        ("FONTNAME", (0, -1), (-1, -1), PDF_FONT_BOLD),
    ]))
    story += [
        table,
        Spacer(1, 6 * mm),
        Paragraph(f"<b>Trạng thái thanh toán:</b> {escape(str(data['ghi_chu']))}", normal),
        Spacer(1, 18 * mm),
    ]
    sign_table = Table(
        [["Người thuê", "Người thu tiền"], ["(Ký và ghi rõ họ tên)", "(Ký và ghi rõ họ tên)"]],
        colWidths=[87 * mm, 87 * mm], rowHeights=[8 * mm, 8 * mm]
    )
    sign_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(sign_table)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        f"Ngày xuất phiếu: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle("RightDate", parent=normal, alignment=TA_RIGHT, fontSize=8)
    ))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue(), total, electric_used, water_used


init_db()

# ======================================
# SIDEBAR - ĐƠN GIÁ & CẤU HÌNH
# ======================================
st.sidebar.header("⚙️ ĐƠN GIÁ ĐIỆN NƯỚC")
gia_dien = st.sidebar.number_input("⚡ Giá điện (đ/kWh)", min_value=0, value=3500, step=100)
gia_nuoc = st.sidebar.number_input("💧 Giá nước (đ/m³)", min_value=0, value=15000, step=500)
phi_khac = st.sidebar.number_input("📦 Phí khác (wifi, vệ sinh...)", min_value=0, value=150000, step=10000)
so_phong = st.sidebar.slider("Số lượng phòng", min_value=1, max_value=100, value=10, step=1)

col_nam, col_thang = st.sidebar.columns(2)
now = datetime.now()
with col_nam:
    years = list(range(now.year - 1, now.year + 6))
    nam_chon = st.selectbox("Chọn năm:", years, index=years.index(now.year))
with col_thang:
    idx_thang_chon = st.selectbox(
        "Chọn tháng:", list(range(1, 13)),
        index=now.month - 1, format_func=lambda x: f"Tháng {x}"
    )
thang_chon = f"Tháng {idx_thang_chon}/{nam_chon}"

# ======================================
# NHẬP / CẬP NHẬT PHÒNG
# ======================================
st.header(f"📋 Nhập số liệu - {thang_chon}")
phong = st.selectbox(
    "Chọn phòng cần nhập dữ liệu:",
    range(1, so_phong + 1),
    format_func=lambda x: f"Phòng {x}",
    key=f"select_room_{nam_chon}_{idx_thang_chon}_{so_phong}"
)

saved = load_bill(nam_chon, idx_thang_chon, phong)
if saved:
    data = {
        "gia_phong": saved["room_price"],
        "ten_nguoi_o": saved["tenant_name"],
        "so_dien_thoai": saved["tenant_phone"],
        "thong_tin_nguoi_o": saved["tenant_info"],
        "dien_cu": saved["electric_old"],
        "dien_moi": saved["electric_new"],
        "nuoc_cu": saved["water_old"],
        "nuoc_moi": saved["water_new"],
        "ghi_chu": saved["note"],
    }
else:
    dien_cu, nuoc_cu = get_previous_readings(nam_chon, idx_thang_chon, phong)
    data = {
        "gia_phong": 2500000,
        "ten_nguoi_o": "",
        "so_dien_thoai": "",
        "thong_tin_nguoi_o": "",
        "dien_cu": dien_cu,
        "dien_moi": dien_cu,
        "nuoc_cu": nuoc_cu,
        "nuoc_moi": nuoc_cu,
        "ghi_chu": "Chưa thanh toán",
    }

st.subheader(f"🏠 Cập nhật: Phòng {phong} ({thang_chon})")
with st.form(key=f"room_form_{nam_chon}_{idx_thang_chon}_{phong}"):
    c1, c2, c3 = st.columns(3)
    with c1:
        gia_phong_input = st.number_input("Giá phòng (VNĐ)", min_value=0, value=int(data["gia_phong"]), step=50000)
        ten_nguoi_o_input = st.text_input("Họ tên người ở", value=data["ten_nguoi_o"])
        so_dien_thoai_input = st.text_input("Số điện thoại", value=data["so_dien_thoai"])
        thong_tin_nguoi_o_input = st.text_area("Thông tin người ở thêm", value=data["thong_tin_nguoi_o"], placeholder="Ví dụ: số CCCD (nếu cần), số người ở, ghi chú...")
    with c2:
        dien_cu_input = st.number_input("Số điện CŨ (kWh)", min_value=0, value=int(data["dien_cu"]), step=1)
        dien_moi_input = st.number_input("Số điện MỚI (kWh)", min_value=0, value=int(data["dien_moi"]), step=1)
        nuoc_cu_input = st.number_input("Số nước CŨ (m³)", min_value=0, value=int(data["nuoc_cu"]), step=1)
        nuoc_moi_input = st.number_input("Số nước MỚI (m³)", min_value=0, value=int(data["nuoc_moi"]), step=1)
    with c3:
        ghi_chu_input = st.selectbox(
            "Trạng thái thanh toán",
            ["Chưa thanh toán", "Đã thanh toán"],
            index=0 if data["ghi_chu"] != "Đã thanh toán" else 1
        )
        st.caption(f"Giá điện: {gia_dien:,} VNĐ/kWh".replace(",", "."))
        st.caption(f"Giá nước: {gia_nuoc:,} VNĐ/m³".replace(",", "."))
        st.caption(f"Phí khác: {phi_khac:,} VNĐ/tháng".replace(",", "."))
    submitted = st.form_submit_button("💾 Lưu thông tin phòng", type="primary", use_container_width=True)

if submitted:
    data = {
        "gia_phong": gia_phong_input,
        "ten_nguoi_o": ten_nguoi_o_input.strip(),
        "so_dien_thoai": so_dien_thoai_input.strip(),
        "thong_tin_nguoi_o": thong_tin_nguoi_o_input.strip(),
        "dien_cu": dien_cu_input,
        "dien_moi": dien_moi_input,
        "nuoc_cu": nuoc_cu_input,
        "nuoc_moi": nuoc_moi_input,
        "ghi_chu": ghi_chu_input,
    }
    save_bill(nam_chon, idx_thang_chon, phong, data)
    st.success(f"Đã lưu dữ liệu Phòng {phong} - {thang_chon} vào SQLite.")
    st.rerun()

# ======================================
# BẢNG TỔNG HỢP
# ======================================
st.divider()
st.header(f"📊 Bảng tổng hợp tiền trọ - {thang_chon}")
ket_qua = []
tong_doanh_thu = 0
for i in range(1, so_phong + 1):
    saved = load_bill(nam_chon, idx_thang_chon, i)
    if saved:
        d = {
            "gia_phong": saved["room_price"],
            "dien_cu": saved["electric_old"],
            "dien_moi": saved["electric_new"],
            "nuoc_cu": saved["water_old"],
            "nuoc_moi": saved["water_new"],
            "ghi_chu": saved["note"],
            "ten_nguoi_o": saved["tenant_name"],
            "so_dien_thoai": saved["tenant_phone"],
        }
    else:
        dien_cu, nuoc_cu = get_previous_readings(nam_chon, idx_thang_chon, i)
        d = {
            "gia_phong": 2500000, "dien_cu": dien_cu, "dien_moi": dien_cu,
            "nuoc_cu": nuoc_cu, "nuoc_moi": nuoc_cu,
            "ghi_chu": "Chưa thanh toán", "ten_nguoi_o": "", "so_dien_thoai": ""
        }
    so_dien = max(int(d["dien_moi"]) - int(d["dien_cu"]), 0)
    so_nuoc = max(int(d["nuoc_moi"]) - int(d["nuoc_cu"]), 0)
    tien_dien = so_dien * gia_dien
    tien_nuoc = so_nuoc * gia_nuoc
    tong_tien = int(d["gia_phong"]) + tien_dien + tien_nuoc + phi_khac
    tong_doanh_thu += tong_tien
    ket_qua.append({
        "Phòng": f"Phòng {i}",
        "Người ở": d["ten_nguoi_o"],
        "Số điện cũ": d["dien_cu"],
        "Số điện mới": d["dien_moi"],
        "Tiền điện": tien_dien,
        "Số nước cũ": d["nuoc_cu"],
        "Số nước mới": d["nuoc_moi"],
        "Tiền nước": tien_nuoc,
        "Giá phòng": d["gia_phong"],
        "Phí khác": phi_khac,
        "Tổng tiền": tong_tien,
        "Trạng thái": d["ghi_chu"],
    })

df = pd.DataFrame(ket_qua)
st.dataframe(
    df, use_container_width=True, hide_index=True,
    column_config={
        "Giá phòng": st.column_config.NumberColumn(format="%d"),
        "Tiền điện": st.column_config.NumberColumn(format="%d"),
        "Tiền nước": st.column_config.NumberColumn(format="%d"),
        "Phí khác": st.column_config.NumberColumn(format="%d"),
        "Tổng tiền": st.column_config.NumberColumn(format="%d"),
    }
)
st.metric(f"💰 TỔNG THU TIỀN CÁC PHÒNG ({thang_chon})", money(tong_doanh_thu))
csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label=f"📥 Xuất báo cáo {thang_chon} (CSV)",
    data=csv,
    file_name=f"Bang_Tien_Phong_Thang_{idx_thang_chon}_{nam_chon}.csv",
    mime="text/csv"
)

# ======================================
# XUẤT HÓA ĐƠN PDF RIÊNG TỪNG PHÒNG
# ======================================
st.divider()
st.header("🧾 Xuất phiếu thu PDF theo từng phòng")
pdf_room = st.selectbox(
    "Chọn phòng cần xuất PDF:",
    range(1, so_phong + 1),
    format_func=lambda x: f"Phòng {x}",
    key=f"pdf_room_{nam_chon}_{idx_thang_chon}_{so_phong}"
)
pdf_saved = load_bill(nam_chon, idx_thang_chon, pdf_room)
if pdf_saved:
    pdf_data = {
        "gia_phong": pdf_saved["room_price"],
        "ten_nguoi_o": pdf_saved["tenant_name"],
        "so_dien_thoai": pdf_saved["tenant_phone"],
        "thong_tin_nguoi_o": pdf_saved["tenant_info"],
        "dien_cu": pdf_saved["electric_old"],
        "dien_moi": pdf_saved["electric_new"],
        "nuoc_cu": pdf_saved["water_old"],
        "nuoc_moi": pdf_saved["water_new"],
        "ghi_chu": pdf_saved["note"],
    }
else:
    e_old, w_old = get_previous_readings(nam_chon, idx_thang_chon, pdf_room)
    pdf_data = {
        "gia_phong": 2500000, "ten_nguoi_o": "", "so_dien_thoai": "",
        "thong_tin_nguoi_o": "", "dien_cu": e_old, "dien_moi": e_old,
        "nuoc_cu": w_old, "nuoc_moi": w_old, "ghi_chu": "Chưa thanh toán"
    }
pdf_bytes, pdf_total, _, _ = create_invoice_pdf(
    nam_chon, idx_thang_chon, pdf_room, pdf_data,
    (gia_dien, gia_nuoc, phi_khac)
)
st.caption(f"Tổng tiền phiếu thu Phòng {pdf_room}: {money(pdf_total)}")
st.download_button(
    label=f"📄 Tải PDF tiền phòng {pdf_room} - {thang_chon}",
    data=pdf_bytes,
    file_name=f"Phieu_Thu_Phong_{pdf_room}_Thang_{idx_thang_chon}_{nam_chon}.pdf",
    mime="application/pdf",
    key=f"download_pdf_{nam_chon}_{idx_thang_chon}_{pdf_room}"
)

st.info(
    "Lưu ý: SQLite lưu dữ liệu trong file quan_ly_tien_tro.db. "
    "Nếu triển khai trên Streamlit Community Cloud, hệ thống tệp có thể bị đặt lại khi ứng dụng khởi động lại hoặc triển khai lại; "
    "muốn dữ liệu bền vững lâu dài trên cloud, hãy dùng ổ lưu trữ bền vững hoặc cơ sở dữ liệu bên ngoài."
)
