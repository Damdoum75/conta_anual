import io
from datetime import datetime
from typing import Dict, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.units import inch


def generar_pdf_modelo100(
    datos_usuario: Dict[str, Any],
    resultado: Dict[str, Any],
    year: int = 2025
) -> bytes:
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a365d'),
        spaceAfter=30,
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#2d3748'),
        spaceBefore=20,
        spaceAfter=10,
    )
    
    elements.append(Paragraph(f"Modelo 100 - IRPF {year}", title_style))
    elements.append(Spacer(1, 10))
    
    elements.append(Paragraph("DATOS DEL DECLARANTE", heading_style))
    
    datos_personales = [
        ["Email:", datos_usuario.get("email", "N/A")],
        ["NIE/NIF:", datos_usuario.get("nie", "N/A")],
        ["Estado Civil:", datos_usuario.get("civil_status", "N/A")],
        ["Comunidad Autónoma:", datos_usuario.get("autonomous_community", "N/A")],
        ["Tipo Declaración:", "Conjunta" if datos_usuario.get("is_joint_declaration") else "Individual"],
    ]
    
    t_personales = Table(datos_personales, colWidths=[2*inch, 3*inch])
    t_personales.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(t_personales)
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph("RESULTADO DE LA DECLARACIÓN", heading_style))
    
    resultado_data = [
        ["Base Imponible:", f"{resultado.get('base_imponible', 0):.2f} €"],
        ["Cuota Íntegra:", f"{resultado.get('cuota_integral', 0):.2f} €"],
        ["Deducciones:", f"-{resultado.get('deduccion_total', 0):.2f} €"],
        ["Cuota Neta:", f"{resultado.get('cuota_neta', 0):.2f} €"],
        ["Retenciones:", f"{resultado.get('retenciones', 0):.2f} €"],
    ]
    
    resultado_tipo = resultado.get("resultado_tipo", "a_pagar")
    resultado_monto = resultado.get("resultado", 0)
    
    if resultado_tipo == "a_pagar":
        resultado_data.append(["A PAGAR:", f"{abs(resultado_monto):.2f} €"])
    else:
        resultado_data.append(["A DEVOLVER:", f"{abs(resultado_monto):.2f} €"])
    
    t_resultado = Table(resultado_data, colWidths=[2*inch, 3*inch])
    t_resultado.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(t_resultado)
    elements.append(Spacer(1, 20))
    
    if resultado.get("tramos_aplicados"):
        elements.append(Paragraph("TRAMOS APLICADOS", heading_style))
        
        tramos_data = [["Tramo", "Base", "Tipo", "Cuota"]]
        for t in resultado["tramos_aplicados"]:
            tramos_data.append([
                f"Tramo {t.get('tramo', '')}",
                f"{t.get('base_gravable', 0):.2f} €",
                f"{t.get('tipo', 0)}%",
                f"{t.get('cuota', 0):.2f} €",
            ])
        
        t_tramos = Table(tramos_data, colWidths=[1.5*inch, 1.5*inch, 1*inch, 1.5*inch])
        t_tramos.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d3748')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        elements.append(t_tramos)
    
    elements.append(Spacer(1, 30))
    
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.gray,
        spaceBefore=20,
    )
    
    disclaimer = """
    <b>CLÁUSULA DE RESPONSABILIDAD:</b><br/>
    Este documento ha sido generado automáticamente basándose en los datos proporcionados por el usuario. 
    Los cálculos contenidos en este Modelo 100 son orientativos y no sustituyen el asesoramiento de un profesional 
    fiscal cualificado (asesor fiscal). El usuario es responsable de verificar la exactitud de todos los datos 
    antes de presentar su declaración ante la Agencia Tributaria (Hacienda).<br/><br/>
    RentaFácil España no se hace responsable de errores, omisiones o consecuencias derivadas del uso de este documento.
    """
    
    elements.append(Paragraph(disclaimer, disclaimer_style))
    
    elements.append(Spacer(1, 20))
    
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(f"<i>Documento generado el {fecha}</i>", styles['Normal']))
    
    doc.build(elements)
    
    buffer.seek(0)
    return buffer.getvalue()