from django.http import HttpResponse
from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
import logging
import io
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from ..models import Participacao, ValoresParticipacao, AprovacaoSetor, Setor, Funcionario
from ..services.calculos import get_data_pagamento
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('participacao.log'),
        logging.StreamHandler()
    ]
)

def gestor_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Faça login para continuar.")
            return redirect('Participacao:login')
        try:
            if request.user.funcionario.tipo_acesso not in ['gestor', 'master_admin'] and not request.user.is_superuser:
                messages.error(request, "Permissão negada.")
                return redirect('Participacao:login')
        except ObjectDoesNotExist:
            messages.error(request, "Usuário não associado.")
            return redirect('Participacao:login')
        return view_func(request, *args, **kwargs)
    return wrapper

@login_required
@gestor_required
def gerar_relatorio_pdf(request):
    logger.info(f"Usuário {request.user.username} gerando relatório PDF")
    selected_trimestre = request.GET.get('trimestre', '')
    if not selected_trimestre:
        logger.error("Nenhum trimestre selecionado")
        messages.error(request, "Selecione um trimestre.")
        return redirect('Participacao:detalhes_calculo_participacao')
    try:
        valores = ValoresParticipacao.objects.get(trimestre=selected_trimestre)
    except ValoresParticipacao.DoesNotExist:
        logger.error(f"Valores não configurados para {selected_trimestre}")
        messages.error(request, f"Configure os valores para {selected_trimestre}.")
        return redirect('Participacao:detalhes_calculo_participacao')
    participacoes = Participacao.objects.filter(trimestre=selected_trimestre, funcionario__setor__recebe_participacao=True)
    total_normal = float(valores.documentos_normais) - float(valores.deducao_normal)
    valor_normal = total_normal * 0.40
    total_diferenciada = float(valores.documentos_diferenciados) - float(valores.deducao_diferenciada)
    valor_diferenciada = total_diferenciada * 0.30
    total_bruto = valor_normal + valor_diferenciada
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()
    styles['Title'].fontSize = 16
    styles['Heading2'].fontSize = 14
    elements.append(Paragraph(f"Relatório de Participação - {selected_trimestre}", styles['Title']))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Valores Iniciais", styles['Heading2']))
    data = [
        ["Documentos Normais", f"R$ {total_normal:.2f}"],
        ["Documentos Diferenciados", f"R$ {total_diferenciada:.2f}"],
        ["Valor Normal (40%)", f"R$ {valor_normal:.2f}"],
        ["Valor Diferenciado (30%)", f"R$ {valor_diferenciada:.2f}"],
        ["Valor Total Bruto", f"R$ {total_bruto:.2f}"],
    ]
    table = Table(data, colWidths=[10*cm, 5*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Detalhes por Funcionário", styles['Heading2']))
    data = [["Funcionário", "Setor", "Tipo de Participação", "Percentual", "Dias Trabalhados", "Valor Bruto (R$)", "Valor Final (R$)"]]
    total_bruto = 0.0
    total_final = 0.0
    for p in participacoes:
        f = p.funcionario
        data.append([
            f.nome, f.setor.nome if f.setor else "Não informado", f.tipo_participacao.title(),
            f"{f.percentual_participacao:.2f}%", str(p.dias_trabalhados), f"{p.valor_bruto:.2f}", f"{p.final_participacao:.2f}"
        ])
        total_bruto += p.valor_bruto
        total_final += p.final_participacao
    col_widths = [5*cm, 3*cm, 3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Totais Calculados", styles['Heading2']))
    data = [["Total Bruto Calculado", f"R$ {total_bruto:.2f}"], ["Total Final Calculado", f"R$ {total_final:.2f}"]]
    table = Table(data, colWidths=[10*cm, 5*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="relatorio_{selected_trimestre}.pdf"'
    response.write(pdf)
    return response

@login_required
@gestor_required
def gerar_relatorio_excel(request):
    logger.info(f"Usuário {request.user.username} gerando relatório Excel")
    selected_trimestre = request.GET.get('trimestre', '')
    if not selected_trimestre:
        logger.error("Nenhum trimestre selecionado")
        messages.error(request, "Selecione um trimestre.")
        return redirect('Participacao:detalhes_calculo_participacao')
    try:
        valores = ValoresParticipacao.objects.get(trimestre=selected_trimestre)
    except ValoresParticipacao.DoesNotExist:
        logger.error(f"Valores não configurados para {selected_trimestre}")
        messages.error(request, f"Configure os valores para {selected_trimestre}.")
        return redirect('Participacao:detalhes_calculo_participacao')
    participacoes = Participacao.objects.filter(trimestre=selected_trimestre, funcionario__setor__recebe_participacao=True)
    total_normal = float(valores.documentos_normais) - float(valores.deducao_normal)
    valor_normal = total_normal * 0.40
    total_diferenciada = float(valores.documentos_diferenciados) - float(valores.deducao_diferenciada)
    valor_diferenciada = total_diferenciada * 0.30
    total_bruto = valor_normal + valor_diferenciada
    wb = Workbook()
    ws = wb.active
    ws.title = f"Relatório {selected_trimestre}"
    ws.append(["Valores Iniciais"])
    ws.append(["Documentos Normais", f"R$ {total_normal:.2f}"])
    ws.append(["Documentos Diferenciados", f"R$ {total_diferenciada:.2f}"])
    ws.append(["Valor Normal (40%)", f"R$ {valor_normal:.2f}"])
    ws.append(["Valor Diferenciado (30%)", f"R$ {valor_diferenciada:.2f}"])
    ws.append(["Valor Total Bruto", f"R$ {total_bruto:.2f}"])
    ws.append([])
    ws.append(["Detalhes por Funcionário"])
    ws.append(["Funcionário", "Setor", "Tipo de Participação", "Percentual", "Dias Trabalhados", "Valor Bruto (R$)", "Valor Final (R$)"])
    total_bruto = 0.0
    total_final = 0.0
    for p in participacoes:
        f = p.funcionario
        ws.append([f.nome, f.setor.nome if f.setor else "Não informado", f.tipo_participacao.title(), f"{f.percentual_participacao:.2f}%", str(p.dias_trabalhados), f"{p.valor_bruto:.2f}", f"{p.final_participacao:.2f}"])
        total_bruto += p.valor_bruto
        total_final += p.final_participacao
    ws.append([])
    ws.append(["Totais Calculados"])
    ws.append(["Total Bruto Calculado", f"R$ {total_bruto:.2f}"])
    ws.append(["Total Final Calculado", f"R$ {total_final:.2f}"])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="relatorio_{selected_trimestre}.xlsx"'
    response.write(buffer.getvalue())
    buffer.close()
    return response

@login_required
@gestor_required
def detalhes_calculo_participacao(request):
    trimestres = sorted(set(p.trimestre for p in Participacao.objects.all()), reverse=True)
    selected_trimestre = request.GET.get('trimestre', '')
    if not selected_trimestre:
        return render(request, 'Participacao/detalhes_calculo_participacao.html', {'trimestres': trimestres, 'selected_trimestre': selected_trimestre})
    try:
        valores = ValoresParticipacao.objects.get(trimestre=selected_trimestre)
    except ValoresParticipacao.DoesNotExist:
        logger.error(f"Valores não configurados para {selected_trimestre}")
        messages.error(request, f"Configure os valores para {selected_trimestre}.")
        return redirect('Participacao:detalhes_calculo_participacao')
    total_normal = float(valores.documentos_normais) - float(valores.deducao_normal)
    valor_normal = total_normal * 0.40
    total_diferenciada = float(valores.documentos_diferenciados) - float(valores.deducao_diferenciada)
    valor_diferenciada = total_diferenciada * 0.30
    total_bruto = valor_normal + valor_diferenciada
    setores_aptos = Setor.objects.filter(recebe_participacao=True)
    participacoes = Participacao.objects.filter(trimestre=selected_trimestre, funcionario__setor__in=setores_aptos)
    detalhes = [{
        'funcionario': p.funcionario, 'setor': p.funcionario.setor.nome if p.funcionario.setor else "Não informado",
        'tipo_participacao': p.funcionario.tipo_participacao, 'percentual_participacao': p.funcionario.percentual_participacao,
        'dias_trabalhados': p.dias_trabalhados, 'valor_bruto': round(p.valor_bruto, 2), 'valor_final': round(p.final_participacao, 2)
    } for p in participacoes]
    total_bruto_calculado = sum(p.valor_bruto for p in participacoes)
    total_final_calculado = sum(p.final_participacao for p in participacoes)
    return render(request, 'Participacao/detalhes_calculo_participacao.html', {
        'trimestres': trimestres, 'selected_trimestre': selected_trimestre, 'detalhes': detalhes,
        'total_normal': total_normal, 'valor_normal': valor_normal, 'total_diferenciada': total_diferenciada,
        'valor_diferenciada': valor_diferenciada, 'total_bruto': total_bruto, 'funcionarios_aptos_count': participacoes.count(),
        'num_funcionarios_faturamento': participacoes.filter(funcionario__setor__nome="Faturamento").count(),
        'num_funcionarios_demais': participacoes.exclude(funcionario__setor__nome="Faturamento").count(),
        'valor_x': valor_normal / participacoes.count() if participacoes.count() > 0 else 0,
        'valor_por_funcionario_faturamento': (valor_diferenciada * 0.55) / participacoes.filter(funcionario__setor__nome="Faturamento").count() if participacoes.filter(funcionario__setor__nome="Faturamento").count() > 0 else 0,
        'valor_por_funcionario_demais': (valor_diferenciada * 0.45) / participacoes.exclude(funcionario__setor__nome="Faturamento").count() if participacoes.exclude(funcionario__setor__nome="Faturamento").count() > 0 else 0,
        'valor_bruto_faturamento': (valor_normal / participacoes.count() + (valor_diferenciada * 0.55) / participacoes.filter(funcionario__setor__nome="Faturamento").count()) if participacoes.count() > 0 and participacoes.filter(funcionario__setor__nome="Faturamento").count() > 0 else 0,
        'valor_bruto_demais': (valor_normal / participacoes.count() + (valor_diferenciada * 0.45) / participacoes.exclude(funcionario__setor__nome="Faturamento").count()) if participacoes.count() > 0 and participacoes.exclude(funcionario__setor__nome="Faturamento").count() > 0 else 0,
        'total_bruto_calculado': round(total_bruto_calculado, 2), 'total_final_calculado': round(total_final_calculado, 2)
    })

@login_required
@gestor_required
def download_extrato_pdf(request, funcionario_nome):
    logger.info(f"Usuário {request.user.username} baixando extrato PDF para {funcionario_nome}")
    trimester = request.GET.get('trimestre', '')
    try:
        funcionario = Funcionario.objects.get(nome=funcionario_nome)
        participacao = Participacao.objects.get(funcionario=funcionario, trimester=trimestre)
    except (Funcionario.DoesNotExist, Participacao.DoesNotExist):
        logger.error(f"{funcionario_nome} ou participação {trimester} não encontrada")
        return HttpResponse("Funcionario ou participação não encontrada.", status=404)
    incluir_trimestre = request.GET.get('incluir_trimestre', '1') == '1'
    incluir_setor = request.GET.get('incluir_setor', '1') == '1'
    incluir_valor_base = request.GET.get('incluir_valor_base', '1') == '1'
    incluir_atrasos = request.GET.get('incluir_atrasos', '1') == '1'
    incluir_saidas_antecipadas = request.GET.get('incluir_saidas_antecipadas', '1') == '1'
    incluir_atestados = request.GET.get('incluir_atestados', '1') == '1'
    incluir_faltas_justificadas = request.GET.get('incluir_faltas_justificadas', '1') == '1'
    incluir_faltas_nao_justificadas = request.GET.get('incluir_faltas_nao_justificadas', '1') == '1'
    incluir_desconto_total = request.GET.get('incluir_desconto_total', '1') == '1'
    incluir_valor_final = request.GET.get('incluir_valor_final', '1') == '1'
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, f"Extrato de Participação - {funcionario_nome}")
    y = 700
    texto = []
    if incluir_trimestre:
        texto.append(f"Trimestre: {participacao.trimestre}")
    if incluir_setor:
        texto.append(f"Setor: {funcionario.setor.nome if funcionario.setor else 'Não informado'}")
    if incluir_valor_base:
        texto.append(f"Valor Base: R$ {funcionario.setor.valor_base if funcionario.setor else 0:.2f}")
    if incluir_atrasos:
        texto.append(f"Atrasos: {participacao.atraso_count} (Penalidade: {participacao.atraso_e_saida_penalty*100:.2f}%)")
    if incluir_saidas_antecipadas:
        texto.append(f"Saídas Antecipadas: {participacao.saida_antecipada_count} (Penalidade: {participacao.atraso_e_saida_penalty*100:.2f}%)")
    if incluir_atestados:
        texto.append(f"Atestados: {participacao.atestado_count} (Penalidade: {participacao.atestado_penalty*100:.2f}%)")
    if incluir_faltas_justificadas:
        texto.append(f"Faltas Justificadas: {participacao.falta_justificada_count} (Penalidade: {participacao.falta_justificada_penalty*100:.2f}%)")
    if incluir_faltas_nao_justificadas:
        texto.append(f"Faltas Não Justificadas: {participacao.falta_nao_justificada_count} (Penalidade: {participacao.falta_nao_justificada_penalty*100:.2f}%)")
    if incluir_desconto_total:
        texto.append(f"Desconto Total: {participacao.desconto_total:.2f}%")
    if incluir_valor_final:
        texto.append(f"Valor Final: R$ {participacao.final_participacao:.2f}")
    for linha in texto:
        p.setFont("Helvetica", 12)
        p.drawString(100, y, linha)
        y -= 20
    p.showPage()
    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="extrato_{funcionario_nome}_{trimester}.pdf"'
    return response

@login_required
@gestor_required
def download_relatorio_pagamento(request):
    logger.info(f"Usuário {request.user.username} baixando relatório de pagamento")
    trimester = request.GET.get('trimestre', '')
    if not trimester:
        logger.error("Trimestre não especificado")
        return HttpResponse("Trimestre não especificado.", status=400)
    aprovacoes = AprovacaoSetor.objects.filter(trimester=trimester, status='pago')
    if request.user.funcionario.type_acesso == 'gestor':
        aprovacoes = aprovacoes.filter(setor__in=request.user.funcionario.setores_responsaveis.all())
    if not aprovacoes.exists():
        logger.error(f"Nenhum setor pago em {trimester}")
        return HttpResponse(f"Nenhum setor pago em {trimester}.", status=404)
    participacoes = Participacao.objects.filter(
        trimester=trimester, funcionario__setor__in=[a.setor for a in aprovacoes]
    ).select_related('funcionario__setor')
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, f"Relatório de Pagamento - {trimester}")
    y = 700
    total_bruto = 0
    total_liquido = 0
    participacoes_por_setor = defaultdict(list)
    for p in participacoes:
        setor_nome = p.funcionario.setor.nome if p.funcionario.setor else "Não informado"
        participacoes_por_setor[setor_nome].append(p)
    for setor_nome, ps in participacoes_por_setor.items():
        y -= 20
        p.setFont("Helvetica-Bold", 12)
        p.drawString(100, y, f"Setor: {setor_nome}")
        y -= 20
        for p in ps:
            texto = [
                f"Funcionário: {p.funcionario.nome}",
                f"Valor Bruto: R$ {p.funcionario.setor.valor_base if p.funcionario.setor else 0:.2f}",
                f"Valor Líquido: R$ {p.final_participacao:.2f}",
                f"Desconto Total: {p.desconto_total:.2f}%",
                "-" * 50
            ]
            for linha in texto:
                p.setFont("Helvetica", 10)
                p.drawString(120, y, linha)
                y -= 15
                if y < 50:
                    p.showPage()
                    y = 750
            total_bruto += float(p.funcionario.setor.valor_base if p.funcionario.setor else 0)
            total_liquido += float(p.final_participacao)
        y -= 20
        p.setFont("Helvetica-Bold", 12)
        p.drawString(100, y, f"Total Bruto: R$ {total_bruto:.2f}")
        y -= 20
        p.drawString(100, y, f"Total Líquido: R$ {total_liquido:.2f}")
    p.showPage()
    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="relatorio_pagamento_{trimester}.pdf"'
    return response