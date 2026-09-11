import os
import json
import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def generate_qr_code(ticket_data, output_dir):
    """
    Generates a high-quality QR code containing ticket verification data.
    """
    os.makedirs(output_dir, exist_ok=True)
    ticket_id = ticket_data['id']
    qr_filename = f"ticket_qr_{ticket_id}.png"
    qr_filepath = os.path.join(output_dir, qr_filename)

    # Pass type labels
    pass_type = ticket_data.get('pass_type', 'single')
    pass_type_labels = {
        'single': 'SINGLE JOURNEY TICKET',
        'daily': '1-DAY UNLIMITED PASS',
        'student': 'STUDENT CONCESSION MONTHLY PASS (50% OFF)',
        'monthly': 'MONTHLY COMMUTER PASS (30 DAYS)'
    }
    pass_label = pass_type_labels.get(pass_type, 'STANDARD PASS')

    # Verification payload
    payload = {
        "ticket_id": ticket_id,
        "ticket_number": f"BP-{ticket_id:06d}",
        "passenger": ticket_data['user_name'],
        "email": ticket_data['user_email'],
        "source": ticket_data['source'],
        "destination": ticket_data['destination'],
        "travel_date": ticket_data['travel_date'],
        "seat_number": ticket_data['seat_number'],
        "departure_time": ticket_data['departure_time'],
        "pass_type": pass_label,
        "valid_until": ticket_data.get('valid_until') or ticket_data['travel_date'],
        "fare": f"Rs. {ticket_data.get('amount_paid', ticket_data['price']):.2f}",
        "status": "VALID_ACTIVE"
    }

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=8,
        border=3,
    )
    qr.add_data(json.dumps(payload))
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1E3A8A", back_color="white")
    img.save(qr_filepath)

    return qr_filename, qr_filepath

def generate_pdf_ticket(ticket_data, qr_filepath, output_dir):
    """
    Generates a professional bus pass / ticket PDF using ReportLab.
    """
    os.makedirs(output_dir, exist_ok=True)
    ticket_id = ticket_data['id']
    pdf_filename = f"ticket_pass_{ticket_id}.pdf"
    pdf_filepath = os.path.join(output_dir, pdf_filename)

    doc = SimpleDocTemplate(
        pdf_filepath,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    story = []
    styles = getSampleStyleSheet()

    # Pass type labels
    pass_type = ticket_data.get('pass_type', 'single')
    pass_type_labels = {
        'single': 'SINGLE JOURNEY TICKET',
        'daily': '1-DAY UNLIMITED PASS',
        'student': 'STUDENT CONCESSION (50% OFF)',
        'monthly': 'MONTHLY COMMUTER (30 DAYS)'
    }
    pass_label = pass_type_labels.get(pass_type, 'STANDARD PASS')
    valid_until = ticket_data.get('valid_until') or ticket_data['travel_date']

    # Custom styles
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#4B5563'),
        alignment=1
    )

    section_header = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1E40AF')
    )

    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#374151')
    )

    value_style = ParagraphStyle(
        'Value',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#111827')
    )

    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#1E40AF'),
        alignment=1
    )

    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b>CLOUDBUS TRANSIT SYSTEM</b>", title_style),
        ],
        [
            Paragraph("Official Digital E-Pass & Boarding Ticket | CodeAlpha Transit Project", subtitle_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[520])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#EFF6FF')),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#3B82F6')),
        ('PADDING', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    # Pass Category Ribbon
    category_data = [
        [
            Paragraph(f"🎫 <b>PASS CATEGORY:</b> {pass_label}", badge_style)
        ]
    ]
    category_table = Table(category_data, colWidths=[520])
    category_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF3C7') if pass_type == 'student' else colors.HexColor('#E0E7FF')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#F59E0B') if pass_type == 'student' else colors.HexColor('#6366F1')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.append(category_table)
    story.append(Spacer(1, 10))

    # 2. Status & Ticket ID Bar
    status_data = [
        [
            Paragraph(f"<b>TICKET ID:</b> #BP-{ticket_id:06d}", label_style),
            Paragraph(f"<b>STATUS:</b> <font color='#059669'><b>CONFIRMED & ACTIVE</b></font>", label_style),
            Paragraph(f"<b>VALIDITY:</b> {ticket_data['travel_date']} to {valid_until}", label_style)
        ]
    ]
    status_table = Table(status_data, colWidths=[150, 180, 190])
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F3F4F6')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#D1D5DB')),
    ]))
    story.append(status_table)
    story.append(Spacer(1, 12))

    # 3. Passenger & Journey Details Grid
    student_id_text = f"<b>Student ID:</b> {ticket_data.get('student_id_number')}" if ticket_data.get('student_id_number') else "<b>ID Type:</b> Govt / Digital ID"
    amount = ticket_data.get('amount_paid', ticket_data['price'])

    passenger_info = [
        [Paragraph("<b>Passenger Details</b>", section_header), Paragraph("<b>Journey & Transit Details</b>", section_header)],
        [
            Paragraph(f"<b>Name:</b> {ticket_data['user_name']}", value_style),
            Paragraph(f"<b>Route:</b> {ticket_data['source']} ➔ {ticket_data['destination']}", value_style)
        ],
        [
            Paragraph(f"<b>Email:</b> {ticket_data['user_email']}", value_style),
            Paragraph(f"<b>Start Date:</b> <b>{ticket_data['travel_date']}</b>", value_style)
        ],
        [
            Paragraph(f"<b>User ID:</b> #{ticket_data['user_id']}", value_style),
            Paragraph(f"<b>Departure Time:</b> {ticket_data['departure_time']}", value_style)
        ],
        [
            Paragraph(student_id_text, value_style),
            Paragraph(f"<b>Assigned Seat:</b> <font color='#1D4ED8' size='12'><b>Seat #{ticket_data['seat_number']}</b></font>", value_style)
        ],
        [
            Paragraph(f"<b>Amount Paid:</b> <font color='#047857' size='12'><b>Rs. {amount:.2f}</b></font>", value_style),
            Paragraph(f"<b>Distance:</b> {ticket_data['distance_km']} km (AC Express)", value_style)
        ]
    ]

    details_table = Table(passenger_info, colWidths=[260, 260])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#DBEAFE')),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#DBEAFE')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#93C5FD')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 12))

    # 4. QR Code & Boarding Instructions
    qr_img = RLImage(qr_filepath, width=1.5*inch, height=1.5*inch)
    
    instructions = (
        "<b>Terms & Conductor Validation Instructions:</b><br/>"
        "1. Conductor will scan the QR code above using the official Scanner Portal to mark boarding.<br/>"
        "2. For Student Passes, please present your valid Student College/School ID Card during inspection.<br/>"
        "3. Monthly & Daily passes allow unlimited round journeys on this route during validity.<br/>"
        "4. Keep this digital PDF or printed copy available on your mobile device.<br/>"
        "5. Support & Inquiries: support@cloudbus.com"
    )
    inst_para = Paragraph(instructions, ParagraphStyle('Inst', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=colors.HexColor('#374151')))

    qr_section_data = [
        [
            Paragraph("<b>Live QR Validator</b><br/><font size='7' color='#6B7280'>Scan with Conductor Scanner</font>", subtitle_style),
            Paragraph("<b>Passenger Guidelines & Validity Terms</b>", section_header)
        ],
        [
            qr_img,
            inst_para
        ]
    ]
    qr_table = Table(qr_section_data, colWidths=[150, 370])
    qr_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F9FAFB')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#D1D5DB')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (0,1), (0,1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(qr_table)
    story.append(Spacer(1, 14))

    # 5. Footer
    footer_text = Paragraph(
        "Generated securely by CloudBus Transit System | Created by Arjun Rathod | CodeAlpha Internship Project",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7.5, leading=10, alignment=1, textColor=colors.HexColor('#9CA3AF'))
    )
    story.append(footer_text)

    # Build document
    doc.build(story)
    return pdf_filename, pdf_filepath