import io
import pandas as pd
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_excel_report(df: pd.DataFrame, sheet_name: str = "Report") -> bytes:
    """
    Generates a spreadsheet binary stream from a pandas DataFrame.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()

def generate_pdf_report(title: str, headers: list, rows: list, is_landscape: bool = False) -> bytes:
    """
    Generates a formatted PDF report with wrapped text cells, alternate row backgrounds, 
    and repeated headers using ReportLab.
    """
    buffer = io.BytesIO()
    pagesize = landscape(letter) if is_landscape else letter
    
    # 0.5 inch margins
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=pagesize, 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="TitleStyle",
        parent=styles["Heading1"],
        fontSize=15,
        textColor=colors.HexColor("#1e3d59"),
        spaceAfter=10
    )
    cell_style = ParagraphStyle(
        name="CellStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=9
    )
    header_style = ParagraphStyle(
        name="HeaderStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=9,
        textColor=colors.white,
        fontName="Helvetica-Bold"
    )
    
    story = []
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 8))
    
    # Convert cell values to Paragraphs to support text wrapping with safety truncation
    data = []
    data.append([Paragraph(str(h), header_style) for h in headers])
    for row in rows:
        clean_row = []
        for cell in row:
            val_str = str(cell) if cell is not None else ""
            if len(val_str) > 300:
                val_str = val_str[:297] + "..."
            clean_row.append(Paragraph(val_str, cell_style))
        data.append(clean_row)
        
    # Calculate column widths proportionally to fit margins (landscape: 792x612, portrait: 612x792)
    # Printable area width = pagesize width - 72
    printable_width = pagesize[0] - 72
    col_count = len(headers)
    
    # Proportional column width allocation based on max content length
    max_lens = [len(str(h)) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            if idx < len(max_lens):
                max_lens[idx] = max(max_lens[idx], len(str(cell)) if cell is not None else 0)
                
    total_len = sum(max_lens)
    if total_len > 0 and col_count > 0:
        # Guarantee a minimum width to prevent too-narrow columns
        min_width = max(25, int(printable_width / (col_count * 2)))
        remaining_width = printable_width - (col_count * min_width)
        col_widths = []
        for ml in max_lens:
            w = min_width + (ml / total_len) * remaining_width
            col_widths.append(w)
    else:
        col_widths = [printable_width / col_count] * col_count
    
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1e3d59")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
    ]))
    
    story.append(t)
    doc.build(story)
    return buffer.getvalue()
