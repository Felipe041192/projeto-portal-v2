from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import logging
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from collections import defaultdict
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from ..models import Participacao, Setor, Funcionario, Evento, AprovacaoSetor, UserActionLog, LoginAttempt, ValoresParticipacao, RegraParticipacao
from ..services.calculos import get_data_pagamento, get_trimestre, recalcular_participacao_funcionario, calcular_penalidades
from django.core.paginator import Paginator
import pandas as pd
import datetime
import random
import string
import json
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
from django.contrib.auth import authenticate, login as auth_login, logout
import openpyxl
from ..forms import PlanilhaParticipacaoForm

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('participacao.log'),
        logging.StreamHandler()
    ]
)

from ..decorators import gestor_required

@login_required
@gestor_required
@transaction.atomic
def editar_dias_trabalhados(request, participacao_id):
    participacao = get_object_or_404(Participacao, id=participacao_id)
    if request.method == 'POST':
        dias_trabalhados = int(request.POST.get('dias_trabalhados', 0))
        if dias_trabalhados < 0 or dias_trabalhados > 90:
            logger.error(f"Dias inválidos para {participacao.funcionario.nome}: {dias_trabalhados}")
            messages.error(request, "Dias trabalhados devem estar entre 0 e 90.")
            return redirect('Participacao:editar_funcionario', id=participacao.funcionario.id)
        participacao.dias_trabalhados = dias_trabalhados
        participacao.dias_trabalhados_edited = True
        participacao.save()
        logger.info(f"Dias trabalhados atualizados para {participacao.funcionario.nome}: {dias_trabalhados}")
        messages.success(request, f"Dias trabalhados atualizados para {participacao.funcionario.nome}.")
        recalcular_participacao_funcionario(participacao.funcionario, participacao.trimestre)
        return redirect('Participacao:editar_funcionario', id=participacao.funcionario.id)
    return redirect('Participacao:editar_funcionario', id=participacao.funcionario.id)

@login_required
def index(request):
    logger.info(f"Usuário {request.user.username} acessando página inicial")
    if request.session.get_expiry_age() < 0:
        logger.info(f"Sessão expirada para {request.user.username}")
        logout(request)
        request.session.flush()
        response = redirect('Participacao:login')
        response.delete_cookie('sessionid')
        messages.info(request, "Sessão expirada. Faça login novamente.")
        return response
    last_activity = request.session.get('last_activity')
    if last_activity and timezone.now() - timezone.datetime.fromisoformat(last_activity) > datetime.timedelta(seconds=1200):
        logger.info(f"Sessão inativa por 20min para {request.user.username}")
        logout(request)
        request.session.flush()
        response = redirect('Participacao:login')
        response.delete_cookie('sessionid')
        messages.info(request, "Sessão expirada por in Unteratividade.")
        return response
    request.session['last_activity'] = timezone.now().isoformat()
    setores = Setor.objects.annotate(total_funcionarios=Count('funcionarios')).order_by('nome')
    dados_setores = {'labels': [s.nome for s in setores], 'data': [s.total_funcionarios for s in setores]}
    logger.info(f"Dados setores: {dados_setores}")
    try:
        pode_ver_participacao = request.user.funcionario.tipo_acesso in ['gestor', 'master_admin']
        logger.debug(f"Usuário {request.user.username} - Tipo: {request.user.funcionario.tipo_acesso}, Pode ver: {pode_ver_participacao}")
    except ObjectDoesNotExist:
        logger.error(f"Usuário {request.user.username} sem Funcionario associado")
        pode_ver_participacao = False
        messages.error(request, "Usuário não associado. Contate o administrador.")
    return render(request, 'participacao/index.html', {'dados_setores': dados_setores, 'pode_ver_participacao': pode_ver_participacao})

@login_required
@gestor_required
def configurar_setores_participacao(request):
    logger.info(f"Usuário {request.user.username} acessando configuração de setores de participação")
    setores = Setor.objects.all().order_by('nome')
    if request.method == 'POST':
        setor_id = request.POST.get('setor_id')
        recebe_participacao = request.POST.get('recebe_participacao') == 'on'
        try:
            setor = Setor.objects.get(id=setor_id)
            setor.recebe_participacao = recebe_participacao
            setor.save()
            logger.info(f"Configuração de participação para {setor.nome} atualizada por {request.user.username}")
            messages.success(request, f"Configuração de {setor.nome} atualizada.")
        except Setor.DoesNotExist:
            logger.error(f"Setor {setor_id} não encontrado")
            messages.error(request, "Setor não encontrado.")
        return redirect('Participacao:configurar_setores_participacao')
    return render(request, 'participacao/configurar_setores_participacao.html', {
        'setores': setores,
    })

@login_required
@gestor_required
@transaction.atomic
def cadastrar_setor(request):
    logger.info(f"Usuário {request.user.username} iniciando cadastro de setor")
    if request.method == 'POST':
        from .forms import SetorForm
        form = SetorForm(request.POST)
        if form.is_valid():
            try:
                setor = form.save()
                logger.info(f"Setor {setor.nome} cadastrado por {request.user.username}")
                messages.success(request, f"Setor '{setor.nome}' cadastrado com sucesso.")
                return redirect('Participacao:configurar_setores_participacao')
            except Exception as e:
                logger.error(f"Erro ao cadastrar setor: {str(e)}")
                messages.error(request, f"Erro ao cadastrar setor: {str(e)}")
        else:
            logger.error(f"Erro no formulário: {form.errors}")
            messages.error(request, "Verifique os dados do formulário.")
    else:
        from .forms import SetorForm
        form = SetorForm()
    return render(request, 'participacao/cadastrar_setor.html', {
        'form': form,
    })

@login_required
@gestor_required
def configurar_regras_participacao(request):
    logger.info(f"Usuário {request.user.username} acessando configuração de regras de participação")
    regras_existentes = RegraParticipacao.objects.all().order_by('data_inicio')
    if request.method == 'POST':
        tipo_regra = request.POST.get('tipo_regra')
        data_inicio = request.POST.get('data_inicio')
        data_fim = request.POST.get('data_fim')
        limite_ocorrencias = request.POST.get('limite_ocorrencias')
        valor_base = request.POST.get('valor_base')
        valor_adicional = request.POST.get('valor_adicional')
        try:
            data_inicio = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
            data_fim = datetime.datetime.strptime(data_fim, '%Y-%m-%d').date() if data_fim else None
            limite_ocorrencias = int(limite_ocorrencias)
            valor_base = float(valor_base.replace(',', '.'))
            valor_adicional = float(valor_adicional.replace(',', '.')) if valor_adicional else 0.0
        except ValueError:
            logger.error("Valores inválidos no formulário")
            messages.error(request, "Insira valores numéricos e datas válidas.")
            return redirect('Participacao:configurar_regras_participacao')
        try:
            with transaction.atomic():
                regra = RegraParticipacao.objects.create(
                    tipo_regra=tipo_regra,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    limite_ocorrencias=limite_ocorrencias,
                    valor_base=valor_base,
                    valor_adicional=valor_adicional
                )
                logger.info(f"Regra para {tipo_regra} criada por {request.user.username}")
                messages.success(request, f"Regra para {tipo_regra} criada com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao criar regra: {str(e)}")
            messages.error(request, f"Erro ao criar regra: {str(e)}")
        return redirect('Participacao:configurar_regras_participacao')
    return render(request, 'participacao/configurar_regras_participacao.html', {
        'regras_existentes': regras_existentes,
    })

@login_required
@gestor_required
def configurar_participacao_setor(request):
    logger.info(f"Usuário {request.user.username} acessando configuração de participação por setor")
    trimestres = ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
    valores_existentes = ValoresParticipacao.objects.all().order_by('trimestre')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            trimestre = request.POST.get('trimestre')
            try:
                valores = ValoresParticipacao.objects.get(trimestre=trimestre)
                valores.delete()
                logger.info(f"Configuração de valores para {trimestre} excluída por {request.user.username}")
                messages.success(request, f"Configuração de valores para {trimestre} excluída.")
            except ValoresParticipacao.DoesNotExist:
                logger.error(f"Configuração para {trimestre} não encontrada")
                messages.error(request, f"Configuração para {trimestre} não encontrada.")
            return redirect('Participacao:configurar_participacao_setor')
        trimestre = request.POST.get('trimestre')
        documentos_normais = request.POST.get('documentos_normais')
        documentos_diferenciados = request.POST.get('documentos_diferenciados')
        deducao_normal = request.POST.get('deducao_normal')
        deducao_diferenciada = request.POST.get('deducao_diferenciada')
        try:
            documentos_normais = float(documentos_normais.replace(',', '.'))
            documentos_diferenciados = float(documentos_diferenciados.replace(',', '.'))
            deducao_normal = float(deducao_normal.replace(',', '.'))
            deducao_diferenciada = float(deducao_diferenciada.replace(',', '.'))
        except ValueError:
            logger.error("Valores inválidos no formulário")
            messages.error(request, "Insira valores numéricos válidos.")
            return redirect('Participacao:configurar_participacao_setor')
        try:
            with transaction.atomic():
                valores, created = ValoresParticipacao.objects.update_or_create(
                    trimestre=trimestre,
                    defaults={
                        'documentos_normais': documentos_normais,
                        'documentos_diferenciados': documentos_diferenciados,
                        'deducao_normal': deducao_normal,
                        'deducao_diferenciada': deducao_diferenciada,
                    }
                )
                logger.info(f"Valores para {trimestre} salvos por {request.user.username}")
                messages.success(request, f"Valores para {trimestre} salvos.")
        except Exception as e:
            logger.error(f"Erro ao salvar valores para {trimestre}: {str(e)}")
            messages.error(request, f"Erro ao salvar valores: {str(e)}")
        return redirect('Participacao:configurar_participacao_setor')
    return render(request, 'participacao/configurar_participacao_setor.html', {
        'trimestres': trimestres,
        'valores_existentes': valores_existentes,
    })

@login_required
@gestor_required
@transaction.atomic
def recalcular_participacao(request):
    logger.info(f"Iniciando recálculo para trimestre {request.GET.get('trimestre')}")
    trimestre = request.GET.get('trimestre')
    if not trimestre:
        logger.error("Nenhum trimestre selecionado")
        messages.error(request, "Selecione um trimestre.")
        return redirect('Participacao:participacao')
    try:
        valores = ValoresParticipacao.objects.get(trimestre=trimestre)
        logger.info(f"Valores encontrados: Doc Normais={valores.documentos_normais}, Dedução={valores.deducao_normal}, Percentual Normal={valores.percentual_normal}")
    except ValoresParticipacao.DoesNotExist:
        logger.error(f"Valores não configurados para {trimestre}")
        messages.error(request, f"Configure os valores para {trimestre}.")
        return redirect('Participacao:configurar_participacao_setor')
    ano, q = map(int, trimestre.split('-Q'))
    data_inicio = pd.Timestamp(f"{ano}-{(q-1)*3+1:02d}-01")
    data_fim = pd.Timestamp(f"{ano}-{(q*3):02d}-{(30 if q<4 else 31)}")
    dias_no_trimestre = 90
    data_pagamento = get_data_pagamento(trimestre)
    logger.debug(f"Trimestre {trimestre}: Início={data_inicio}, Fim={data_fim}, Dias={dias_no_trimestre}, Pagamento={data_pagamento}")
    setores_aptos = Setor.objects.filter(recebe_participacao=True)
    if not setores_aptos.exists():
        logger.error("Nenhum setor apto")
        messages.error(request, "Configure setores aptos.")
        return redirect('Participacao:configurar_setores_participacao')
    funcionarios_aptos = Funcionario.objects.filter(setor__in=setores_aptos)
    if not funcionarios_aptos.exists():
        logger.error("Nenhum funcionário apto")
        messages.error(request, "Nenhum funcionário apto encontrado.")
        return redirect('Participacao:participacao')
    funcionarios_proporcional_fora = []
    funcionarios_normal_no = []
    total_normal = float(valores.documentos_normais) - float(valores.deducao_normal)
    valor_normal = total_normal * (float(valores.percentual_normal) / 100)
    total_diferenciada = float(valores.documentos_diferenciados) - float(valores.deducao_diferenciada)
    valor_t = total_diferenciada * (float(valores.percentual_diferenciada) / 100)
    valor_y = valor_t * (float(valores.percentual_demais) / 100)
    valor_p = valor_t * (float(valores.percentual_faturamento) / 100)
    logger.debug(f"Valores: Normal={valor_normal}, Diferenciada={valor_t}, Y={valor_y}, P={valor_p}")
    grouped = defaultdict(lambda: {
        "atraso_count": 0, "atraso_by_month": defaultdict(int), "saida_antecipada_count": 0,
        "saida_antecipada_by_month": defaultdict(int), "atestado_count": 0, "falta_justificada_count": 0,
        "falta_nao_justificada_count": 0, "falta_meio_turno_count": 0, "falta_meio_turno_by_month": defaultdict(int),
        "falta_dia_todo_count": 0, "falta_dia_todo_by_month": defaultdict(int),
        "esquecimento_ponto_count": 0, "esquecimento_ponto_by_month": defaultdict(int),
        "advertencia_count": 0, "advertencia_by_month": defaultdict(int),
        "compensacao_count": 0, "licenca_maternidade_count": 0, "eventos": [],
        "datas_trabalhadas": set(), "datas_faltas": set()
    })
    eventos = Evento.objects.filter(trimestre=trimestre)
    logger.debug(f"Eventos carregados: {eventos.count()}")
    for evento in eventos:
        if not evento.funcionario or evento.minutos < 0:
            logger.warning(f"Evento inválido: ID={evento.id}, Func={evento.funcionario}, Min={evento.minutos}")
            continue
        emp = evento.funcionario.nome
        mes_ano_display = evento.mes_ano_display
        grouped[emp]["eventos"].append({
            "tipo": evento.type, "data": evento.data.strftime('%d/%m/%Y'), "mes_ano": evento.mes_ano,
            "mes_ano_display": mes_ano_display, "dia": evento.dia, "minutos": evento.minutos,
            "status": evento.status, "horas_minutos": evento.horas_minutos, "compensado": getattr(evento, 'compensado', False)
        })
        grouped[emp]["datas_trabalhadas"].add(evento.data.strftime('%Y-%m-%d'))
        if evento.type == "atraso" and not getattr(evento, 'compensado', False) and evento.minutos >= 5:
            grouped[emp]["atraso_count"] += 1
            if 5 <= evento.minutos <= 10:
                grouped[emp]["atraso_by_month"][mes_ano_display] += 1
            elif evento.minutos > 10 and evento.minutos <= 240:
                grouped[emp]["falta_meio_turno_count"] += 1
                grouped[emp]["falta_meio_turno_by_month"][mes_ano_display] += 1
            elif evento.minutos > 240:
                grouped[emp]["falta_dia_todo_count"] += 1
                grouped[emp]["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "saida_antecipada" and not getattr(evento, 'compensado', False) and evento.minutos >= 5:
            grouped[emp]["saida_antecipada_count"] += 1
            if 5 <= evento.minutos <= 10:
                grouped[emp]["saida_antecipada_by_month"][mes_ano_display] += 1
            elif evento.minutos > 10 and evento.minutos <= 240:
                grouped[emp]["falta_meio_turno_count"] += 1
                grouped[emp]["falta_meio_turno_by_month"][mes_ano_display] += 1
            elif evento.minutos > 240:
                grouped[emp]["falta_dia_todo_count"] += 1
                grouped[emp]["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "atestado":
            grouped[emp]["atestado_count"] += 1
        elif evento.type == "falta_justificada":
            grouped[emp]["falta_justificada_count"] += 1
            grouped[emp]["datas_faltas"].add(evento.data.strftime('%Y-%m-%d'))
        elif evento.type == "falta_nao_justificada":
            grouped[emp]["falta_nao_justificada_count"] += 1
            grouped[emp]["datas_faltas"].add(evento.data.strftime('%Y-%m-%d'))
        elif evento.type == "falta_meio_turno":
            grouped[emp]["falta_meio_turno_count"] += 1
            grouped[emp]["falta_meio_turno_by_month"][mes_ano_display] += 1
        elif evento.type == "falta_dia_todo":
            grouped[emp]["falta_dia_todo_count"] += 1
            grouped[emp]["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "esquecimento_ponto":
            grouped[emp]["esquecimento_ponto_count"] += 1
            grouped[emp]["esquecimento_ponto_by_month"][mes_ano_display] += 1
        elif evento.type == "advertencia":
            grouped[emp]["advertencia_count"] += 1
            grouped[emp]["advertencia_by_month"][mes_ano_display] += 1
        elif evento.type == "compensacao":
            grouped[emp]["compensacao_count"] += 1
        elif evento.type == "licenca_maternidade":
            grouped[emp]["licenca_maternidade_count"] += 1
    funcionarios_aptos_count = 0
    total_bruto_calculado = 0.0
    def compare_trimestres(t1, t2):
        if not t1 or not t2: return False
        a1, q1 = map(int, t1.split('-Q'))
        a2, q2 = map(int, t2.split('-Q'))
        return a1 > a2 or (a1 == a2 and q1 > q2)
    def trimestre_anterior(t1, t2):
        if not t1 or not t2: return False
        a1, q1 = map(int, t1.split('-Q'))
        a2, q2 = map(int, t2.split('-Q'))
        return a1 < a2 or (a1 == a2 and q1 < q2)
    funcionarios_com_dias = []
    for funcionario in funcionarios_aptos:
        emp = funcionario.nome
        eventos = grouped[emp]["eventos"]
        data_evento = min(pd.to_datetime(e["data"], format='%d/%m/%Y') for e in eventos).date() if eventos else data_inicio.date()
        logger.debug(f"Processando {emp}: Eventos={len(eventos)}, Tipo={funcionario.tipo_participacao}, Admissão={funcionario.data_admissao}")
        if funcionario.data_demissao and funcionario.data_demissao < data_pagamento:
            logger.info(f"{emp} desligado antes de {data_pagamento}")
            continue
        trimestre_admissao = get_trimestre(funcionario.data_admissao) if funcionario.data_admissao else None
        if trimestre_admissao and funcionario.tipo_participacao == 'proporcional' and compare_trimestres(trimestre, trimestre_admissao):
            funcionarios_proporcional_fora.append({'nome': emp, 'data_admissao': funcionario.data_admissao.strftime('%d/%m/%Y'), 'id': funcionario.id})
            logger.warning(f"{emp} proporcional fora de {trimestre_admissao}")
        if trimestre_admissao and funcionario.tipo_participacao == 'normal' and trimestre == trimestre_admissao:
            funcionarios_normal_no.append({'nome': emp, 'data_admissao': funcionario.data_admissao.strftime('%d/%m/%Y'), 'id': funcionario.id})
            logger.warning(f"{emp} normal em {trimestre}")
        if funcionario.trimestre_inicio_participacao and compare_trimestres(funcionario.trimestre_inicio_participacao, trimestre):
            p, _ = Participacao.objects.get_or_create(funcionario=funcionario, trimestre=trimestre, defaults={'data_pagamento': data_pagamento, 'editavel': True})
            p.dias_trabalhados = 0
            p.valor_bruto = 0.0
            p.final_participacao = 0.0
            p.desconto_total = 0.0
            p.penalidades_totais = 0.0
            p.save()
            continue
        if funcionario.tipo_participacao == 'menor_aprendiz':
            p, _ = Participacao.objects.get_or_create(funcionario=funcionario, trimestre=trimestre, defaults={'data_pagamento': data_pagamento, 'editavel': True})
            p.dias_trabalhados = 0
            p.valor_bruto = 0.0
            p.final_participacao = 0.0
            p.desconto_total = 0.0
            p.penalidades_totais = 0.0
            p.save()
            continue
        dias_trabalhados = 90
        data_inicio_func = data_inicio
        data_fim_func = data_fim
        if funcionario.data_admissao and pd.Timestamp(funcionario.data_admissao) > data_inicio:
            data_inicio_func = pd.Timestamp(funcionario.data_admissao)
        if funcionario.data_demissao and pd.Timestamp(funcionario.data_demissao) < data_fim:
            data_fim_func = pd.Timestamp(funcionario.data_demissao)
        if funcionario.tipo_participacao == 'proporcional':
            datas_no_intervalo = set()
            current_date = data_inicio_func
            while current_date <= data_fim_func:
                datas_no_intervalo.add(current_date.strftime('%Y-%m-%d'))
                current_date += datetime.timedelta(days=1)
            dias_calculados = len(datas_no_intervalo - grouped[emp]["datas_faltas"])
        else:
            dias_calculados = 90
        try:
            p = Participacao.objects.get(funcionario=funcionario, trimestre=trimestre)
            dias_trabalhados_manual = p.dias_trabalhados
            if p.dias_trabalhados_edited and dias_trabalhados_manual > 0:
                dias_trabalhados = dias_trabalhados_manual
            elif funcionario.proporcional and funcionario.proporcional > 0:
                dias_trabalhados = funcionario.proporcional
            else:
                dias_trabalhados = dias_calculados
        except Participacao.DoesNotExist:
            if funcionario.proporcional and funcionario.proporcional > 0:
                dias_trabalhados = funcionario.proporcional
            else:
                dias_trabalhados = dias_calculados
        if funcionario.tipo_participacao == 'proporcional' and dias_trabalhados < 15:
            p, _ = Participacao.objects.get_or_create(funcionario=funcionario, trimestre=trimestre, defaults={'data_pagamento': data_pagamento, 'editavel': True})
            p.dias_trabalhados = dias_trabalhados
            p.valor_bruto = 0.0
            p.final_participacao = 0.0
            p.desconto_total = 0.0
            p.penalidades_totais = 0.0
            p.save()
            continue
        if funcionario.tipo_participacao != 'proporcional' and (dias_trabalhados == 0 and not eventos):
            p, _ = Participacao.objects.get_or_create(funcionario=funcionario, trimestre=trimestre, defaults={'data_pagamento': data_pagamento, 'editavel': True})
            p.dias_trabalhados = dias_trabalhados
            p.valor_bruto = 0.0
            p.final_participacao = 0.0
            p.desconto_total = 0.0
            p.penalidades_totais = 0.0
            p.save()
            continue
        funcionarios_aptos_count += 1
        funcionarios_com_dias.append((funcionario, dias_trabalhados))
    if funcionarios_proporcional_fora:
        messages.warning(request, json.dumps({'tipo': 'proporcional_fora_trimestre', 'trimestre': trimestre, 'funcionarios': funcionarios_proporcional_fora}))
    if funcionarios_normal_no:
        messages.warning(request, json.dumps({'tipo': 'normal_no_trimestre', 'trimestre': trimestre, 'funcionarios': funcionarios_normal_no}))
    primeiro_valor_x = valor_normal / funcionarios_aptos_count if funcionarios_aptos_count > 0 else 0.0
    num_faturamento = sum(1 for f, _ in funcionarios_com_dias if f.setor and f.setor.nome == "Faturamento")
    num_demais = funcionarios_aptos_count - num_faturamento
    valor_y_por_func = valor_y / num_demais if num_demais > 0 else 0.0
    valor_p_por_func = valor_p / num_faturamento if num_faturamento > 0 else 0.0
    valor_bruto_faturamento = round(primeiro_valor_x + valor_p_por_func, 2)
    valor_bruto_demais = round(primeiro_valor_x + valor_y_por_func, 2)
    if valor_bruto_faturamento > 5000 or valor_bruto_demais > 5000:
        messages.warning(request, "Valores brutos altos. Verifique os dados.")
    for funcionario, dias_trabalhados in funcionarios_com_dias:
        emp = funcionario.nome
        eventos = grouped[emp]["eventos"]
        data_evento = min(pd.to_datetime(e["data"], format='%d/%m/%Y') for e in eventos).date() if eventos else data_inicio.date()
        setor_nome = funcionario.setor.nome if funcionario.setor else "Não informado"
        valor_bruto = valor_bruto_faturamento if setor_nome == "Faturamento" else valor_bruto_demais
        total_bruto_calculado += valor_bruto
        detalhes_descontos = []
        desconto_total, penalidades_totais, detalhes, _, _, _, _, _, _, _, _, _, _ = calcular_penalidades(grouped[emp], valor_bruto, data_evento)
        valor_liquido = valor_bruto * (1 - desconto_total / 100)
        detalhes_descontos.extend(detalhes)
        percentual = float(funcionario.percentual_participacao)
        if percentual < 100:
            valor_antes = valor_liquido
            valor_liquido *= (percentual / 100)
            detalhes_descontos.append({"motivo": f"Percentual {percentual}%", "value": round(valor_antes - valor_liquido, 2)})
        if funcionario.tipo_participacao == 'proporcional' and dias_trabalhados < 90:
            valor_antes = valor_liquido
            valor_liquido = (valor_bruto / 90) * dias_trabalhados
            desconto = valor_antes - valor_liquido
            detalhes_descontos.append({"motivo": f"Proporcional {dias_trabalhados} dias", "value": round(desconto, 2)})
        abono_value = float(funcionario.abono_valor)
        abono_type = funcionario.abono_type
        abono_ativo = funcionario.abono_ativo
        if abono_ativo:
            valor_antes = valor_liquido
            abono = (valor_bruto * abono_value / 100) if abono_type == 'percentage' else abono_value
            valor_liquido += abono
            detalhes_descontos.append({"motivo": f"Abono {abono_type} {abono_value}", "value": -round(abono, 2)})
        ajuste_manual = float(p.ajuste_manual) if 'p' in locals() else 0.0
        valor_liquido += ajuste_manual
        valor_liquido = max(0, round(valor_liquido, 0))
        if ajuste_manual:
            detalhes_descontos.append({"motivo": "Ajuste Manual", "value": -round(ajuste_manual, 2)})
        p, _ = Participacao.objects.get_or_create(funcionario=funcionario, trimestre=trimestre, defaults={'data_pagamento': data_pagamento, 'editavel': True})
        p.atraso_count = grouped[emp]["atraso_count"]
        p.saida_antecipada_count = grouped[emp]["saida_antecipada_count"]
        p.atestado_count = grouped[emp]["atestado_count"]
        p.falta_justificada_count = grouped[emp]["falta_justificada_count"]
        p.falta_nao_justificada_count = grouped[emp]["falta_nao_justificada_count"]
        p.falta_meio_turno_count = grouped[emp]["falta_meio_turno_count"]
        p.falta_dia_todo_count = grouped[emp]["falta_dia_todo_count"]
        p.esquecimento_ponto_count = grouped[emp]["esquecimento_ponto_count"]
        p.compensacao_count = grouped[emp]["compensacao_count"]
        p.advertencia_count = grouped[emp]["advertencia_count"]
        p.licenca_maternidade_count = grouped[emp]["licenca_maternidade_count"]
        p.desconto_total = desconto_total / 100
        p.penalidades_totais = penalidades_totais / 100
        p.valor_bruto = valor_bruto
        p.final_participacao = valor_liquido
        p.fator_proporcional = dias_trabalhados / 90 if dias_trabalhados < 90 else 1.0
        p.ajuste_manual = ajuste_manual
        p.detalhes_descontos = detalhes_descontos
        p.atraso_by_month = dict(grouped[emp]["atraso_by_month"])
        p.saida_antecipada_by_month = dict(grouped[emp]["saida_antecipada_by_month"])
        p.dias_trabalhados = dias_trabalhados
        p.dias_trabalhados_edited = p.dias_trabalhados_edited
        p.save()
        logger.info(f"{emp}: Bruto={valor_bruto}, Líquido={valor_liquido}")
    logger.info(f"Total Bruto: {total_bruto_calculado}, Aptos: {funcionarios_aptos_count}")
    messages.success(request, f"Recálculo para {trimestre} concluído. {funcionarios_aptos_count} aptos.")
    return redirect('Participacao:participacao')

@login_required
@gestor_required
@transaction.atomic
def aprovar_participacao(request):
    if request.method == 'POST':
        trimestre = request.POST.get('trimestre')
        setor_id = request.POST.get('setor_id')
        if not trimestre or not setor_id:
            logger.error(f"Trimestre ou setor ausente: {trimestre}, {setor_id}")
            messages.error(request, "Trimestre ou setor não especificado.")
            return redirect('Participacao:participacao')
        try:
            setor = Setor.objects.get(id=setor_id)
        except Setor.DoesNotExist:
            logger.error(f"Setor {setor_id} não encontrado")
            messages.error(request, "Setor não encontrado.")
            return redirect('Participacao:participacao')
        if request.user.funcionario.tipo_acesso == 'gestor' and setor not in request.user.funcionario.setores_responsaveis.all():
            logger.warning(f"Gestor {request.user.username} sem permissão para {setor.nome}")
            messages.error(request, f"Permissão negada para {setor.nome}.")
            return redirect('Participacao:participacao')
        aprovacao, _ = AprovacaoSetor.objects.get_or_create(setor=setor, trimestre=trimestre, defaults={'status': 'pendente'})
        today = datetime.date.today()
        participacoes = Participacao.objects.filter(trimestre=trimestre, funcionario__setor=setor)
        if not participacoes.exists():
            logger.error(f"Nenhuma participação para {setor.nome} em {trimestre}")
            messages.error(request, f"Nenhuma participação para {setor.nome}.")
            return redirect('Participacao:participacao')
        data_pagamento = participacoes.first().data_pagamento
        if today > data_pagamento:
            logger.warning(f"{trimestre} já pago")
            messages.error(request, f"{trimestre} já pago.")
            return redirect('Participacao:participacao')
        if aprovacao.status in ['aprovado', 'pago']:
            logger.warning(f"{setor.nome} em {trimestre} já {aprovacao.status}")
            messages.error(request, f"{setor.nome} já {aprovacao.status}.")
            return redirect('Participacao:participacao')
        aprovacao.status = 'aprovado'
        aprovacao.save()
        for p in participacoes:
            p.editavel = False
            p.save()
        logger.info(f"{setor.nome} em {trimestre} aprovado por {request.user.username}")
        messages.success(request, f"{setor.nome} em {trimestre} aprovado.")
        return redirect('Participacao:participacao')
    return redirect('Participacao:participacao')

@login_required
@gestor_required
@transaction.atomic
def revogar_aprovacao_participacao(request):
    if request.method == 'POST':
        if not request.user.is_superuser:
            logger.warning(f"{request.user.username} tentou revogar sem permissão")
            messages.error(request, "Apenas Master Admins podem revogar.")
            return redirect('Participacao:participacao')
        trimestre = request.POST.get('trimestre')
        setor_id = request.POST.get('setor_id')
        if not trimestre or not setor_id:
            logger.error(f"Trimestre ou setor ausente: {trimestre}, {setor_id}")
            messages.error(request, "Trimestre ou setor não especificado.")
            return redirect('Participacao:participacao')
        try:
            setor = Setor.objects.get(id=setor_id)
        except Setor.DoesNotExist:
            logger.error(f"Setor {setor_id} não encontrado")
            messages.error(request, "Setor não encontrado.")
            return redirect('Participacao:participacao')
        try:
            aprovacao = AprovacaoSetor.objects.get(setor=setor, trimestre=trimestre)
        except AprovacaoSetor.DoesNotExist:
            logger.error(f"Aprovação para {setor.nome} em {trimestre} não encontrada")
            messages.error(request, f"Aprovação para {setor.nome} não encontrada.")
            return redirect('Participacao:participacao')
        today = datetime.date.today()
        participacoes = Participacao.objects.filter(trimestre=trimestre, funcionario__setor=setor)
        if not participacoes.exists():
            logger.error(f"Nenhuma participação para {setor.nome} em {trimestre}")
            messages.error(request, f"Nenhuma participação para {setor.nome}.")
            return redirect('Participacao:participacao')
        data_pagamento = participacoes.first().data_pagamento
        if today > data_pagamento:
            logger.warning(f"{trimestre} já pago")
            messages.error(request, f"{trimestre} já pago.")
            return redirect('Participacao:participacao')
        if aprovacao.status != 'aprovado':
            logger.warning(f"{setor.nome} em {trimestre} não está aprovado")
            messages.error(request, f"{setor.nome} não está aprovado.")
            return redirect('Participacao:participacao')
        aprovacao.status = 'pendente'
        aprovacao.save()
        for p in participacoes:
            p.editavel = True
            p.save()
        logger.info(f"{setor.nome} em {trimestre} revogado por {request.user.username}")
        messages.success(request, f"{setor.nome} em {trimestre} revogado.")
        return redirect('Participacao:participacao')
    return redirect('Participacao:participacao')

@login_required
@gestor_required
@transaction.atomic
def adicionar_advertencia(request):
    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        trimestre = request.POST.get('trimestre')
        data_advertencia = request.POST.get('data_advertencia')
        motivo = request.POST.get('motivo')
        try:
            funcionario = Funcionario.objects.get(id=funcionario_id)
            participacao = Participacao.objects.get(funcionario=funcionario, trimestre=trimestre)
        except (Funcionario.DoesNotExist, Participacao.DoesNotExist):
            logger.error(f"Funcionario {funcionario_id} ou participação {trimestre} não encontrada")
            messages.error(request, "Funcionario ou participação não encontrada.")
            return redirect('Participacao:funcionarios')
        if participacao.funcionario.setor:
            try:
                aprovacao = AprovacaoSetor.objects.get(setor=participacao.funcionario.setor, trimestre=trimestre)
                if aprovacao.status == 'aprovado':
                    logger.warning(f"Setor {participacao.funcionario.setor.nome} aprovado")
                    messages.error(request, f"Setor {participacao.funcionario.setor.nome} aprovado.")
                    return redirect('Participacao:editar_funcionario', funcionario_id=funcionario_id)
            except AprovacaoSetor.DoesNotExist:
                pass
        try:
            data_advertencia = datetime.datetime.strptime(data_advertencia, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Data inválida: {data_advertencia}")
            messages.error(request, "Data inválida. Use YYYY-MM-DD.")
            return redirect('Participacao:editar_funcionario', funcionario_id=funcionario_id)
        if not motivo or not motivo.strip():
            logger.error("Motivo ausente")
            messages.error(request, "Motivo é obrigatório.")
            return redirect('Participacao:editar_funcionario', funcionario_id=funcionario_id)
        mes_ano = data_advertencia.strftime('%Y-%m')
        mes_ano_display = data_advertencia.strftime('%B %Y').capitalize()
        trimestre_evento = get_trimestre(data_advertencia)
        evento = Evento.objects.create(
            funcionario=funcionario, tipo='advertencia', data=data_advertencia, dia=data_advertencia.strftime('%A'),
            minutos=0, horas_minutos='-', status='-', mes_ano=mes_ano, mes_ano_display=mes_ano_display,
            trimestre=trimestre_evento, is_manual=True, motivo=motivo
        )
        logger.info(f"Advertência criada para {funcionario.nome} em {data_advertencia}")
        recalcular_participacao_funcionario(funcionario, trimestre)
        messages.success(request, "Advertência adicionada. Participação recalculada.")
        return redirect('Participacao:editar_funcionario', funcionario_id=funcionario_id)
    return redirect('Participacao:funcionarios')

@login_required
@gestor_required
def inserir_eventos(request):
    if request.method != 'POST':
        messages.error(request, "Método inválido.")
        return redirect('Participacao:participacao')
    try:
        funcionario_id = request.POST.get('funcionario_id')
        trimestre_filtro = request.POST.get('trimestre_filtro')
        eventos_data = request.POST.getlist('eventos[]')
        eventos_a_excluir = request.POST.getlist('excluir_eventos[]')
        funcionario = Funcionario.objects.get(id=funcionario_id)
        if request.user.funcionario.tipo_acesso == 'gestor' and funcionario.setor not in request.user.funcionario.setores_responsaveis.all():
            logger.warning(f"Gestor {request.user.username} sem permissão para {funcionario.nome}")
            messages.error(request, "Permissão negada.")
            return redirect('Participacao:participacao')
        with transaction.atomic():
            if eventos_a_excluir:
                eventos_excluidos = Evento.objects.filter(id__in=eventos_a_excluir, funcionario=funcionario)
                for e in eventos_excluidos:
                    logger.debug(f"Excluindo {e.tipo} em {e.data}")
                    e.delete()
                messages.success(request, f"{len(eventos_a_excluir)} evento(s) excluído(s).")
            for evento_str in eventos_data:
                try:
                    evento_data = json.loads(evento_str)
                    tipo = evento_data['tipo']
                    data_str = evento_data['data']
                    observacao = evento_data.get('observacao', '')
                    data = datetime.datetime.strptime(data_str, '%Y-%m-%d').date()
                    ano = data.year
                    mes = data.month
                    trimestre = f"{ano}-Q{(mes-1)//3+1}"
                    Evento.objects.create(
                        funcionario=funcionario, tipo=tipo, data=data, mes_ano=f"{ano}-{mes:02d}",
                        mes_ano_display=f"{data.strftime('%B')} {ano}", dia=data.strftime('%A'),
                        minutos=0, horas_minutos="0h 0m", trimestre=trimestre, observacao=observacao, is_manual=True
                    )
                    logger.debug(f"Evento {tipo} criado para {funcionario.nome}")
                except (KeyError, json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Erro ao processar evento: {str(e)}")
                    messages.error(request, f"Erro ao processar evento: {str(e)}")
                    continue
            recalcular_participacao_funcionario(funcionario, trimestre_filtro)
        messages.success(request, "Eventos processados.")
        return redirect(f"/participacao/?trimestre={trimestre_filtro}")
    except Funcionario.DoesNotExist:
        logger.error(f"Funcionario {funcionario_id} não encontrado")
        messages.error(request, "Funcionario não encontrado.")
        return redirect('Participacao:participacao')
    except Exception as e:
        logger.error(f"Erro ao processar eventos: {str(e)}")
        messages.error(request, f"Erro: {str(e)}")
        return redirect('Participacao:participacao')

@login_required
@gestor_required
def listar_eventos(request, funcionario_id):
    try:
        eventos = Evento.objects.filter(funcionario_id=funcionario_id).order_by('-data')
        eventos_data = [{'id': e.id, 'tipo': e.tipo, 'data': e.data.strftime('%d/%m/%Y'), 'mes_ano_display': e.mes_ano_display, 'observacao': e.observacao} for e in eventos]
        return JsonResponse({'eventos': eventos_data})
    except Exception as e:
        logger.error(f"Erro ao listar eventos: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@gestor_required
@transaction.atomic
def alternar_abono(request):
    if request.method != 'POST':
        messages.error(request, "Método inválido.")
        return redirect('Participacao:participacao')
    funcionario_id = request.POST.get('funcionario_id')
    trimestre = request.POST.get('trimestre')
    action = request.POST.get('action')
    abono_type = request.POST.get('abono_type')
    abono_value = request.POST.get('abono_value')
    logger.debug(f"POST: {request.POST}, Func ID: {funcionario_id}, Trimestre: {trimestre}")
    try:
        funcionario = Funcionario.objects.get(id=funcionario_id)
    except Funcionario.DoesNotExist:
        logger.error(f"Funcionario {funcionario_id} não encontrado")
        messages.error(request, "Funcionario não encontrado.")
        return redirect('Participacao:participacao')
    logger.debug(f"Funcionario: {funcionario.nome}, Abono atual: {funcionario.abono_ativo}, {funcionario.abono_valor}, {funcionario.abono_type}")
    if action == 'toggle':
        if funcionario.abono_ativo:
            funcionario.abono_ativo = False
            funcionario.abono_valor = 0
            funcionario.abono_type = 'fixed'
        else:
            try:
                abono_value = float(abono_value)
                if abono_value < 0 or abono_type not in ['fixed', 'percentage']:
                    raise ValueError("Valores inválidos.")
                funcionario.abono_ativo = True
                funcionario.abono_valor = abono_value
                funcionario.abono_type = abono_type
            except (ValueError, TypeError):
                logger.error(f"Valor ou tipo inválido para {funcionario.nome}")
                messages.error(request, "Valor ou tipo de abono inválido.")
                return redirect('Participacao:participacao')
    funcionario.save()
    logger.debug(f"Funcionario salvo: {funcionario.abono_ativo}, {funcionario.abono_valor}, {funcionario.abono_type}")
    try:
        participacao = Participacao.objects.get(funcionario=funcionario, trimestre=trimestre)
        valor_liquido = participacao.final_participacao
        detalhes = participacao.detalhes_descontos or []
        detalhes = [d for d in detalhes if not d["motivo"].startswith("Abono")]
        valor_liquido -= sum(-d["value"] for d in participacao.detalhes_descontos if d["motivo"].startswith("Abono"))
        if funcionario.abono_ativo:
            abono = (participacao.valor_bruto * funcionario.abono_valor / 100) if funcionario.abono_type == "percentage" else float(funcionario.abono_valor)
            valor_liquido += abono
            detalhes.append({"motivo": f"Abono ({funcionario.abono_type}, {funcionario.abono_valor})", "value": -round(abono, 2)})
        valor_liquido = max(0, round(valor_liquido, 0))
        participacao.final_participacao = valor_liquido
        participacao.detalhes_descontos = detalhes
        participacao.save()
        logger.debug(f"Participação atualizada: {valor_liquido}")
    except Participacao.DoesNotExist:
        logger.error(f"Participação não encontrada para {funcionario.nome} em {trimestre}")
        messages.error(request, f"Participação não encontrada para {funcionario.nome}.")
        return redirect('Participacao:participacao')
    messages.success(request, f"Abono alterado para {funcionario.nome}.")
    logger.info(f"Abono alterado para {funcionario.nome} por {request.user.username}")
    return redirect('Participacao:participacao')

@login_required
@gestor_required
def extrato(request, funcionario):
    try:
        f = Funcionario.objects.get(nome=funcionario)
        if request.user.funcionario.tipo_acesso == 'gestor' and f.setor not in request.user.funcionario.setores_responsaveis.all():
            logger.warning(f"Gestor {request.user.username} sem permissão para {funcionario}")
            messages.error(request, "Permissão negada.")
            return redirect('Participacao:participacao')
        trimestre = request.GET.get('trimestre', '')
        p = Participacao.objects.filter(funcionario=f, trimestre=trimestre).first() if trimestre else Participacao.objects.filter(funcionario=f).first()
        if not request.user.is_superuser and datetime.date.today() > p.data_pagamento:
            logger.warning(f"{p.trimestre} pago, acesso negado para {request.user.username}")
            messages.error(request, f"{p.trimestre} já pago.")
            return redirect('Participacao:participacao')
        eventos = f.eventos.filter(trimestre=p.trimestre)
        eventos_por_mes = defaultdict(list)
        for e in eventos:
            mes_ano_display = e.mes_ano_display
            status = "Compensado" if getattr(e, 'compensado', False) else "Dentro da Tolerância" if e.minutos < 5 else "Penalizável" if e.minutos > 10 else "-"
            penalizado = "Sim" if p.__dict__.get(f"{e.tipo}_penalty", 0) > 0 else "Não"
            eventos_por_mes[mes_ano_display].append({'tipo': e.tipo, 'data': e.data.strftime('%d/%m/%Y'), 'minutos': e.minutos, 'status': status, 'penalizado': penalizado})
        meses = sorted(set(e.mes_ano_display for e in eventos))
        resumo = {k: getattr(p, k) * 100 for k in ['atraso_e_saida_penalty', 'atestado_penalty', 'falta_justificada_penalty', 'falta_nao_justificada_penalty', 'falta_meio_turno_penalty', 'falta_dia_todo_penalty', 'esquecimento_ponto_penalty', 'advertencia_penalty', 'licenca_maternidade_penalty', 'desconto_total'] if hasattr(p, k)}
        proporcional = f"Proporcional a {p.dias_trabalhados} dias" if f.tipo_participacao == 'proporcional' and p.dias_trabalhados < 90 else None
        return render(request, 'participacao/extrato.html', {
            'funcionario': funcionario, 'eventos_por_mes': dict(eventos_por_mes), 'meses_ordenados': meses,
            'resumo': resumo, 'trimestre': p.trimestre, 'participacao_base': p.valor_bruto,
            'total_descontado': p.valor_bruto * p.desconto_total / 100, 'total_percent': p.desconto_total,
            'proporcional_info': proporcional
        })
    except (Funcionario.DoesNotExist, Participacao.DoesNotExist):
        logger.error(f"{funcionario} não encontrado ou sem participação")
        messages.error(request, "Funcionario ou participação não encontrada.")
        return redirect('Participacao:participacao')

@login_required
@gestor_required
def participacao(request):
    logger.info(f"Usuário {request.user.username} acessando participação")
    funcionario_filtro = request.GET.get('funcionario', '').strip()
    setor_filtro = request.GET.get('setor', '')
    trimestre_filtro = request.GET.get('trimestre', '')
    data_atual = datetime.date.today()
    ultimo_trimestre = get_trimestre(data_atual)
    logger.debug(f"Último trimestre: {ultimo_trimestre}")
    setores = list(Setor.objects.filter(recebe_participacao=True).values_list('nome', flat=True).distinct())
    trimestres_presentes = list(Participacao.objects.values_list('trimestre', flat=True).distinct())
    trimestre_exibicao = trimestre_filtro or ('2024-Q4' if '2024-Q4' in trimestres_presentes else max(trimestres_presentes)) if trimestres_presentes else ''
    participacoes = Participacao.objects.select_related('funcionario__setor').filter(
        funcionario__setor__recebe_participacao=True, valor_bruto__gt=0.0
    ).order_by('-trimestre')
    if funcionario_filtro:
        participacoes = participacoes.filter(funcionario__nome__icontains=funcionario_filtro)
    if setor_filtro:
        participacoes = participacoes.filter(funcionario__setor__nome=setor_filtro)
    if trimestre_exibicao:
        participacoes = participacoes.filter(trimestre=trimestre_exibicao)
    paginator = Paginator(participacoes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    total_bruto = sum(float(p.valor_bruto) if p.valor_bruto else 0.0 for p in page_obj)
    total_liquido = sum(float(p.final_participacao) if p.final_participacao else 0.0 for p in page_obj)
    # Correção da consulta para funcionarios_incompletos
    # Filtra usuários sem associação a Funcionario ou sem senha utilizável
    usuarios_sem_funcionario = User.objects.exclude(id__in=Funcionario.objects.values('usuario_id'))
    usuarios_sem_senha = [u for u in usuarios_sem_funcionario if not u.has_usable_password()]
    funcionarios_incompletos = len(set(Funcionario.objects.filter(
        Q(data_admissao__isnull=True) | Q(usuario__isnull=True) | Q(usuario__in=usuarios_sem_senha)
    ).distinct()))
    funcionarios_incompletos = len(set(Funcionario.objects.filter(
        Q(data_admissao__isnull=True) | Q(usuario__isnull=True) | Q(usuario__in=usuarios_sem_senha)
    ).distinct()))
    if trimestre_exibicao and not ValoresParticipacao.objects.filter(trimestre=trimestre_exibicao).exists():
        logger.warning(f"Valores não configurados para {trimestre_exibicao}")
        messages.warning(request, f"Configure valores para {trimestre_exibicao}.")
    trimestres = Participacao.objects.values_list('trimestre', flat=True).distinct().order_by('-trimestre')
    tentativas_maliciosas = LoginAttempt.objects.filter(is_malicious=True).order_by('-timestamp')
    logger.debug(f"Dados enviados: page_obj={[(p.funcionario.nome, p.trimestre, p.valor_bruto, p.final_participacao) for p in page_obj]}")
    return render(request, 'participacao/participacao.html', {
        'page_obj': page_obj, 'funcionario_filtro': funcionario_filtro, 'setor_filtro': setor_filtro,
        'trimestre_filtro': trimestre_exibicao, 'setores': setores, 'trimestres': trimestres,
        'trimestres_presentes': trimestres_presentes, 'ultimo_trimestre': ultimo_trimestre,
        'total_bruto': total_bruto, 'total_liquido': total_liquido, 'funcionarios_incompletos': funcionarios_incompletos,
        'tentativas_maliciosas_count': tentativas_maliciosas.count(), 'tentativas_maliciosas': list(tentativas_maliciosas)
    })

@login_required
@gestor_required
def editar_funcionario(request, funcionario_id):
    logger.info(f"Usuário {request.user.username} editando funcionário {funcionario_id}")
    is_master_admin = request.user.is_superuser
    try:
        funcionario = Funcionario.objects.get(id=funcionario_id)
    except Funcionario.DoesNotExist:
        logger.error(f"Funcionario {funcionario_id} não encontrado")
        messages.error(request, "Funcionario não encontrado.")
        return redirect('Participacao:funcionarios')
    if not is_master_admin and funcionario.setor not in request.user.funcionario.setores_responsaveis.all():
        logger.warning(f"Sem permissão para {funcionario_id}")
        messages.error(request, "Permissão negada.")
        return redirect('Participacao:funcionarios')
    participacoes = Participacao.objects.filter(funcionario=funcionario).order_by('-trimestre')
    trimestres = [f"{y}-Q{q}" for y in range(datetime.date.today().year-5, datetime.date.today().year+2) for q in range(1, 5) if y < datetime.date.today().year or (y == datetime.date.today().year and q <= (datetime.date.today().month-1)//3+2)]
    if request.method == 'POST':
        logger.debug(f"Dados POST: {request.POST}")
        from .forms import FuncionarioForm
        form = FuncionarioForm(request.POST, instance=funcionario, is_master_admin=is_master_admin)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    logger.info(f"{funcionario.nome} atualizado por {request.user.username}")
                    messages.success(request, f"'{funcionario.nome}' atualizado.")
                    return redirect('Participacao:funcionarios')
            except Exception as e:
                logger.error(f"Erro ao atualizar {funcionario.nome}: {str(e)}")
                messages.error(request, f"Erro ao atualizar: {str(e)}")
                messages.error(request, "Erro ao atualizar: {str(e)}")
        else:
            logger.error(f"Erro no formulário: {form.errors}")
            messages.error(request, "Verifique os dados.")
    else:
        from .forms import FuncionarioForm
        form = FuncionarioForm(instance=funcionario, is_master_admin=is_master_admin)
    return render(request, 'participacao/editar_funcionario.html', {
        'form': form, 'funcionario': funcionario, 'participacoes': participacoes,
        'is_master_admin': is_master_admin, 'trimestres': trimestres
    })

@login_required
#@gestor_required
@transaction.atomic
def funcionarios(request):
    logger.info(f"Usuário {request.user.username} acessando lista de funcionários")
    funcionarios = Funcionario.objects.select_related('setor').all()
    nome_filtro = request.GET.get('nome', '').strip()
    setor_filtro = request.GET.get('setor', '')
    if nome_filtro:
        funcionarios = funcionarios.filter(nome__icontains=nome_filtro)
    if setor_filtro:
        funcionarios = funcionarios.filter(setor__id=setor_filtro)
    ordenar_por = request.GET.get('ordenar_por', 'nome')
    direcao = request.GET.get('direcao', 'ASC')
    campos_validos = ['nome', 'setor__nome', 'tipo_acesso']
    if ordenar_por not in campos_validos:
        ordenar_por = 'nome'
    ordenar_por = f'-{ordenar_por}' if direcao == 'DESC' else ordenar_por
    nova_direcao = 'ASC' if direcao == 'DESC' else 'DESC'
    funcionarios = funcionarios.order_by(ordenar_por)
    total_funcionarios = funcionarios.count()
    logger.info(f"Total funcionários: {total_funcionarios}")
    for f in funcionarios:
        logger.debug(f"Funcionario: {f.nome}, Setor: {f.setor.nome if f.setor else 'Nenhum'}, Tipo: {f.tipo_acesso}")
    setores = Setor.objects.all().order_by('nome')
    return render(request, 'participacao/funcionarios.html', {
        'funcionarios': funcionarios, 'setores': setores, 'nome_filtro': nome_filtro,
        'setor_filtro': setor_filtro, 'ordenar_por': ordenar_por.lstrip('-'),
        'direcao': direcao, 'nova_direcao': nova_direcao
    })

@login_required
@gestor_required
@transaction.atomic
def cadastrar_funcionario(request):
    logger.info(f"[CADASTRO] {request.user.username} iniciando cadastro às {timezone.now()}")
    is_master_admin = request.user.is_superuser
    if request.method == 'POST':
        from .forms import FuncionarioForm
        form = FuncionarioForm(request.POST, is_master_admin=is_master_admin)
        if form.is_valid():
            try:
                with transaction.atomic():
                    funcionario = form.save()
                    logger.info(f"{funcionario.nome} criado por {request.user.username}")
                    messages.success(request, f"'{funcionario.nome}' cadastrado.")
                    return redirect('Participacao:funcionarios')
            except Exception as e:
                logger.error(f"Erro ao cadastrar {funcionario.nome}: {str(e)}")
                messages.error(request, f"Erro ao cadastrar: {str(e)}")
        else:
            logger.error(f"Erro no formulário: {form.errors}")
            messages.error(request, "Verifique os dados.")
    else:
        from .forms import FuncionarioForm
        form = FuncionarioForm()
    trimestres = [f"{y}-Q{q}" for y in range(datetime.date.today().year-5, datetime.date.today().year+2) for q in range(1, 5) if y < datetime.date.today().year or (y == datetime.date.today().year and q <= (datetime.date.today().month-1)//3+2)]
    setores = Setor.objects.all().order_by('nome')
    return render(request, 'participacao/cadastrar_funcionario.html', {
        'form': form, 'setores': setores, 'is_master_admin': is_master_admin, 'trimestres': trimestres
    })

def generate_random_username():
    prefix = "user_"
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    username = prefix + suffix
    while User.objects.filter(username=username).exists():
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        username = prefix + suffix
    return username

def generate_random_password():
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choices(characters, k=12))

def login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            logger.info(f"Usuário {username} logado com sucesso")
            return redirect('Participacao:index')
        else:
            logger.warning(f"Tentativa de login falhou para {username}")
            messages.error(request, "Usuário ou senha inválidos.")
    return render(request, 'participacao/login.html')

@login_required
def logout_view(request):
    logger.info(f"Usuário {request.user.username} deslogado")
    logout(request)
    return redirect('Participacao:login')

@login_required
@gestor_required
def importar_planilha_participacao(request):
    if request.method == "POST":
        form = PlanilhaParticipacaoForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES['file']  # Nome do campo no formulário
            if arquivo.name.endswith(('.csv', '.xlsx', '.xls')):
                try:
                    import pandas as pd
                    df = pd.read_excel(arquivo) if arquivo.name.endswith(('.xlsx', '.xls')) else pd.read_csv(arquivo)
                    for index, row in df.iterrows():
                        # Lógica para salvar no banco (ajuste conforme os modelos)
                        # Exemplo: mapeie colunas para Participacao ou Funcionario
                        pass
                    messages.success(request, "Planilha importada com sucesso!")
                    return redirect("Participacao:participacao")
                except Exception as e:
                    messages.error(request, f"Erro ao processar a planilha: {str(e)}")
            else:
                messages.error(request, "Formato de arquivo inválido. Use .csv, .xlsx ou .xls.")
        else:
            messages.error(request, "Erro ao validar o formulário.")
    else:
        form = PlanilhaParticipacaoForm()
        # Passar trimestres para o formulário
        from datetime import datetime
        ultimo_ano = datetime.now().year
        trimestres = [f"{ano}-Q{trim}" for ano in range(ultimo_ano - 2, ultimo_ano + 1) for trim in range(1, 5)]
        return render(request, 'participacao/importar_planilha.html', {'form': form, 'trimestres': trimestres})

@login_required
@gestor_required
def configurar_proporcional(request):
    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        proporcional = request.POST.get('proporcional')
        try:
            funcionario = Funcionario.objects.get(id=funcionario_id)
            funcionario.proporcional = float(proporcional)
            funcionario.save()
            logger.info(f"Proporcional configurado para {funcionario.nome}: {proporcional}")
            messages.success(request, "Configuração proporcional salva.")
        except Exception as e:
            logger.error(f"Erro ao configurar proporcional: {str(e)}")
            messages.error(request, f"Erro: {str(e)}")
    return redirect('Participacao:funcionarios')

@login_required
@gestor_required
def configurar_ajustes_participacao(request):
    if request.method == 'POST':
        participacao_id = request.POST.get('participacao_id')
        ajuste_manual = request.POST.get('ajuste_manual')
        try:
            participacao = Participacao.objects.get(id=participacao_id)
            participacao.ajuste_manual = float(ajuste_manual)
            participacao.final_participacao += float(ajuste_manual)
            participacao.save()
            logger.info(f"Ajuste manual aplicado: {ajuste_manual} para {participacao.funcionario.nome}")
            messages.success(request, "Ajuste manual aplicado.")
        except Exception as e:
            logger.error(f"Erro ao configurar ajuste: {str(e)}")
            messages.error(request, f"Erro: {str(e)}")
    return redirect('Participacao:participacao')

@login_required
@gestor_required
def calcular_participacao(request):
    trimestre = request.GET.get('trimestre')
    if not trimestre:
        messages.error(request, "Selecione um trimestre.")
        return redirect('Participacao:participacao')
    # Placeholder para lógica de cálculo, pode ser expandido
    return recalcular_participacao(request)

@login_required
@gestor_required
def recalcular_funcionario(request, funcionario_id):
    trimestre = request.GET.get('trimestre')
    try:
        funcionario = Funcionario.objects.get(id=funcionario_id)
        recalcular_participacao_funcionario(funcionario, trimestre)
        logger.info(f"Recálculo individual para {funcionario.nome} em {trimestre}")
        messages.success(request, f"Recálculo concluído para {funcionario.nome}.")
    except Exception as e:
        logger.error(f"Erro ao recalcular funcionário: {str(e)}")
        messages.error(request, f"Erro: {str(e)}")
    return redirect('Participacao:editar_funcionario', funcionario_id=funcionario_id)

@login_required
@gestor_required
def detalhes_calculo_participacao(request):
    participacao_id = request.GET.get('participacao_id')
    try:
        participacao = Participacao.objects.get(id=participacao_id)
        return render(request, 'participacao/detalhes_calculo.html', {'participacao': participacao})
    except Participacao.DoesNotExist:
        logger.error(f"Participação {participacao_id} não encontrada")
        messages.error(request, "Participação não encontrada.")
    return redirect('Participacao:participacao')

@login_required
@gestor_required
def gerar_relatorio_pdf(request):
    trimestre = request.GET.get('trimestre')
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.drawString(100, 750, f"Relatório de Participação - {trimestre}")
    participacoes = Participacao.objects.filter(trimestre=trimestre)
    y = 700
    for p in participacoes:
        p.drawString(100, y, f"{p.funcionario.nome}: Bruto={p.valor_bruto}, Líquido={p.final_participacao}")
        y -= 20
    p.showPage()
    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="relatorio_{trimestre}.pdf"'
    logger.info(f"Relatório PDF gerado para {trimestre} por {request.user.username}")
    return response

@login_required
@gestor_required
def gerar_relatorio_excel(request):
    trimestre = request.GET.get('trimestre')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Participacao_{trimestre}"
    ws.append(["Funcionário", "Setor", "Valor Bruto", "Valor Líquido"])
    participacoes = Participacao.objects.filter(trimestre=trimestre)
    for p in participacoes:
        ws.append([p.funcionario.nome, p.funcionario.setor.nome if p.funcionario.setor else "Nenhum", p.valor_bruto, p.final_participacao])
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="relatorio_{trimestre}.xlsx"'
    logger.info(f"Relatório Excel gerado para {trimestre} por {request.user.username}")
    return response

@login_required
@gestor_required
def download_extrato_pdf(request, funcionario_nome):
    trimestre = request.GET.get('trimestre')
    try:
        funcionario = Funcionario.objects.get(nome=funcionario_nome)
        participacao = Participacao.objects.get(funcionario=funcionario, trimestre=trimestre)
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        p.drawString(100, 750, f"Extrato de {funcionario_nome} - {trimestre}")
        p.drawString(100, 730, f"Valor Bruto: {participacao.valor_bruto}")
        p.drawString(100, 710, f"Valor Líquido: {participacao.final_participacao}")
        p.showPage()
        p.save()
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="extrato_{funcionario_nome}_{trimestre}.pdf"'
        logger.info(f"Extrato PDF gerado para {funcionario_nome} em {trimestre}")
        return response
    except Exception as e:
        logger.error(f"Erro ao gerar extrato PDF: {str(e)}")
        messages.error(request, f"Erro: {str(e)}")
    return redirect('Participacao:participacao')

@login_required
@gestor_required
def download_relatorio_pagamento(request):
    trimestre = request.GET.get('trimestre')
    return gerar_relatorio_pdf(request)  # Reutiliza a lógica de PDF

@login_required
@gestor_required
def logs_geral(request):
    logs = UserActionLog.objects.all().order_by('-timestamp')
    return render(request, 'participacao/logs_geral.html', {'logs': logs})

@login_required
@gestor_required
def logs(request, funcionario_id):
    try:
        funcionario = Funcionario.objects.get(id=funcionario_id)
        logs = UserActionLog.objects.filter(funcionario=funcionario).order_by('-timestamp')
        return render(request, 'participacao/logs.html', {'logs': logs, 'funcionario': funcionario})
    except Funcionario.DoesNotExist:
        logger.error(f"Funcionário {funcionario_id} não encontrado")
        messages.error(request, "Funcionário não encontrado.")
    return redirect('Participacao:funcionarios')

@login_required
@gestor_required
def configurar_abono_funcionario(request):
    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        abono_type = request.POST.get('abono_type')
        abono_value = request.POST.get('abono_value')
        try:
            funcionario = Funcionario.objects.get(id=funcionario_id)
            funcionario.abono_type = abono_type
            funcionario.abono_valor = float(abono_value)
            funcionario.abono_ativo = True
            funcionario.save()
            logger.info(f"Abono configurado para {funcionario.nome}: {abono_type}, {abono_value}")
            messages.success(request, "Abono configurado com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao configurar abono: {str(e)}")
            messages.error(request, f"Erro: {str(e)}")
    return redirect('Participacao:funcionarios')