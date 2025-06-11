from django.contrib import messages
from django.shortcuts import render, redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError, ObjectDoesNotExist
import logging
import json
from datetime import date, datetime
from django.utils import timezone
from ..models import RegraParticipacao, Setor, Funcionario, Participacao, ValoresParticipacao, UserActionLog
from ..services.calculos import get_data_pagamento, get_trimestre

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
@user_passes_test(lambda u: u.is_superuser)
@transaction.atomic
def configurar_regras_participacao(request):
    logger.info(f"Usuário {request.user.username} acessando Configurar Regras de Participação")
    data_atual = date.today()
    regras_salvas = RegraParticipacao.objects.all().order_by('indicador', '-data_inicio')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'excluir':
            regra_id = request.POST.get('regra_id')
            try:
                regra = RegraParticipacao.objects.get(id=regra_id)
                regra.delete()
                UserActionLog.objects.create(
                    user=request.user,
                    action_type='delete',
                    description=f"Excluiu regra de participação para {regra.indicador}",
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                messages.success(request, f"Regra para '{regra.indicador}' excluída com sucesso.")
            except RegraParticipacao.DoesNotExist:
                messages.error(request, "Regra não encontrada.")
            except Exception as e:
                logger.error(f"Erro ao excluir regra: {str(e)}")
                messages.error(request, f"Erro ao excluir regra: {str(e)}")
            return redirect('Participacao:configurar_regras_participacao')
        indicador = request.POST.get('indicador').strip()
        periodo = request.POST.get('periodo').strip()  # 'mensal' ou 'trimestral'
        tolerancia = int(request.POST.get('tolerancia'))
        representatividade = float(request.POST.get('representatividade').replace(',', '.'))
        valor_subsequente = float(request.POST.get('valor_subsequente').replace(',', '.'))
        data_inicio = datetime.strptime(request.POST.get('data_inicio'), '%Y-%m-%d').date()
        try:
            if not all([indicador, periodo, tolerancia, representatividade, data_inicio]):
                raise ValueError("Indicador, período, tolerância, representatividade e data de início são obrigatórios.")
            if tolerancia < 0 or representatividade < 0 or valor_subsequente < 0:
                raise ValueError("Tolerância, representatividade e valor subsequente não podem ser negativos.")
            if periodo not in ['mensal', 'trimestral']:
                raise ValueError("Período deve ser 'mensal' ou 'trimestral'.")
            RegraParticipacao.objects.create(
                indicador=indicador,
                periodo=periodo,
                tolerancia=tolerancia,
                representatividade=representatividade,
                valor_subsequente=valor_subsequente,
                data_inicio=data_inicio
            )
            UserActionLog.objects.create(
                user=request.user,
                action_type='create',
                description=f"Criou regra de participação para {indicador} (período: {periodo}, tolerância: {tolerancia})",
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f"Regra para '{indicador}' criada com sucesso.")
        except ValueError as e:
            logger.error(f"Erro ao criar regra: {str(e)}")
            messages.error(request, f"Erro ao criar regra: {str(e)}")
        except Exception as e:
            logger.error(f"Erro inesperado ao criar regra: {str(e)}")
            messages.error(request, f"Erro inesperado: {str(e)}")
        return redirect('Participacao:configurar_regras_participacao')

    return render(request, 'participacao/configurar_regras_participacao.html', {
        'regras_salvas': regras_salvas,
        'data_atual': data_atual,
        'periodos_validos': ['mensal', 'trimestral'],
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
@transaction.atomic
def configurar_participacao_setor(request):
    logger.info(f"Usuário {request.user.username} acessando Configurar Participação por Setor")
    trimestres = ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
    valores_existentes = ValoresParticipacao.objects.all().order_by('trimestre')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            trimestre = request.POST.get('trimestre')
            try:
                valores = ValoresParticipacao.objects.get(trimestre=trimestre)
                valores.delete()
                UserActionLog.objects.create(
                    user=request.user,
                    action_type='delete',
                    description=f"Excluiu configuração de valores para {trimestre}",
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                messages.success(request, f"Configuração de valores para {trimestre} excluída.")
            except ValoresParticipacao.DoesNotExist:
                messages.error(request, f"Configuração para {trimestre} não encontrada.")
            return redirect('Participacao:configurar_participacao_setor')
        trimestre = request.POST.get('trimestre')
        documentos_normais = request.POST.get('documentos_normais')
        documentos_diferenciados = request.POST.get('documentos_diferenciados')
        deducao_normal = request.POST.get('deducao_normal')
        deducao_diferenciada = request.POST.get('deducao_diferenciada')
        percentual_normal = request.POST.get('percentual_normal')
        percentual_diferenciada = request.POST.get('percentual_diferenciada')
        percentual_faturamento = request.POST.get('percentual_faturamento')
        percentual_demais = request.POST.get('percentual_demais')
        try:
            if not all([trimestre, documentos_normais, documentos_diferenciados, deducao_normal, deducao_diferenciada, percentual_normal, percentual_diferenciada, percentual_faturamento, percentual_demais]):
                raise ValueError("Todos os campos são obrigatórios.")
            documentos_normais = float(documentos_normais.replace(',', '.'))
            documentos_diferenciados = float(documentos_diferenciados.replace(',', '.'))
            deducao_normal = float(deducao_normal.replace(',', '.'))
            deducao_diferenciada = float(deducao_diferenciada.replace(',', '.'))
            percentual_normal = float(percentual_normal.replace(',', '.'))
            percentual_diferenciada = float(percentual_diferenciada.replace(',', '.'))
            percentual_faturamento = float(percentual_faturamento.replace(',', '.'))
            percentual_demais = float(percentual_demais.replace(',', '.'))
            if any(v < 0 for v in [documentos_normais, documentos_diferenciados, deducao_normal, deducao_diferenciada, percentual_normal, percentual_diferenciada, percentual_faturamento, percentual_demais]) or percentual_normal + percentual_diferenciada != 100 or percentual_faturamento + percentual_demais != 100:
                raise ValueError("Valores inválidos ou percentuais não somam 100%.")
            ValoresParticipacao.objects.update_or_create(
                trimestre=trimestre,
                defaults={
                    'documentos_normais': documentos_normais,
                    'documentos_diferenciados': documentos_diferenciados,
                    'deducao_normal': deducao_normal,
                    'deducao_diferenciada': deducao_diferenciada,
                    'percentual_normal': percentual_normal,
                    'percentual_diferenciada': percentual_diferenciada,
                    'percentual_faturamento': percentual_faturamento,
                    'percentual_demais': percentual_demais,
                }
            )
            UserActionLog.objects.create(
                user=request.user,
                action_type='update',
                description=f"Atualizou valores de participação para {trimestre}",
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f"Valores para {trimestre} salvos com sucesso.")
        except ValueError as e:
            logger.error(f"Erro ao salvar valores: {str(e)}")
            messages.error(request, f"Erro ao salvar valores: {str(e)}")
        except Exception as e:
            logger.error(f"Erro inesperado ao salvar valores: {str(e)}")
            messages.error(request, f"Erro inesperado: {str(e)}")
        return redirect('Participacao:configurar_participacao_setor')

    return render(request, 'participacao/configurar_participacao_setor.html', {
        'trimestres': trimestres,
        'valores_existentes': valores_existentes,
    })

@login_required
@gestor_required
@transaction.atomic
def configurar_setores_participacao(request):
    logger.info(f"Usuário {request.user.username} acessando Configurar Setores para Participação")
    mostrar_inativos = request.GET.get('mostrar_inativos', 'false') == 'true'
    setores = Setor.objects.filter(ativo=True) if not mostrar_inativos else Setor.objects.all()
    setores = setores.order_by('nome')
    funcionarios = Funcionario.objects.filter(setor__isnull=True)

    if request.method == 'POST':
        action = request.POST.get('action')
        logger.debug(f"Ação recebida: {action}, Dados: {request.POST}")
        if action == 'update':
            with transaction.atomic():
                for setor in setores:
                    recebe_participacao = f'recebe_participacao_{setor.id}' in request.POST
                    novo_nome = request.POST.get(f'nome_{setor.id}', '').strip()
                    if novo_nome and novo_nome != setor.nome:
                        if Setor.objects.filter(nome=novo_nome).exclude(id=setor.id).exists():
                            messages.error(request, f"Nome '{novo_nome}' já em uso.")
                            continue
                        old_nome = setor.nome
                        setor.nome = novo_nome
                        UserActionLog.objects.create(
                            user=request.user,
                            action_type='update',
                            description=f"Alterou nome de '{old_nome}' para '{novo_nome}'",
                            ip_address=request.META.get('REMOTE_ADDR')
                        )
                    setor.recebe_participacao = recebe_participacao
                    setor.save()
            messages.success(request, "Setores atualizados com sucesso.")
        elif action == 'delete' and 'setor_id' in request.POST:
            setor_id = request.POST.get('setor_id')
            try:
                with transaction.atomic():
                    setor = Setor.objects.get(id=setor_id)
                    funcionarios = Funcionario.objects.filter(setor=setor)
                    if funcionarios.exists():
                        setor_padrao, _ = Setor.objects.get_or_create(nome="Não informado", defaults={'valor_base': 0})
                        funcionarios.update(setor=setor_padrao)
                    setor_nome = setor.nome
                    setor.delete()
                    UserActionLog.objects.create(
                        user=request.user,
                        action_type='delete',
                        description=f"Excluiu setor '{setor_nome}'",
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    messages.success(request, f"Setor '{setor_nome}' excluído.")
            except Setor.DoesNotExist:
                messages.error(request, "Setor não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao excluir setor: {str(e)}")
        elif action == 'toggle_active' and 'setor_id' in request.POST:
            setor_id = request.POST.get('setor_id')
            try:
                with transaction.atomic():
                    setor = Setor.objects.get(id=setor_id)
                    setor.ativo = not setor.ativo
                    if not setor.ativo:
                        setor.recebe_participacao = False
                    setor.save()
                    status = "inativado" if not setor.ativo else "ativado"
                    UserActionLog.objects.create(
                        user=request.user,
                        action_type='update',
                        description=f"{status.capitalize()} setor '{setor.nome}'",
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    messages.success(request, f"Setor '{setor.nome}' {status}.")
            except Setor.DoesNotExist:
                messages.error(request, "Setor não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao alterar status: {str(e)}")
        return redirect('Participacao:configurar_setores_participacao')

    return render(request, 'participacao/configurar_setores_participacao.html', {
        'setores': setores,
        'funcionarios': funcionarios,
        'mostrar_inativos': mostrar_inativos,
    })

@login_required
@gestor_required
@transaction.atomic
def configurar_ajustes_participacao(request):
    if request.method == 'POST':
        trimestre = request.POST.get('trimestre')
        if not trimestre:
            messages.error(request, "Selecione um trimestre.")
            return redirect('Participacao:configurar_ajustes_participacao')
        participacoes = Participacao.objects.filter(trimestre=trimestre)
        for p in participacoes:
            ajuste_manual = float(request.POST.get(f'ajuste_manual_{p.id}', 0))
            fator_proporcional = float(request.POST.get(f'fator_proporcional_{p.id}', 1))
            p.ajuste_manual, p.fator_proporcional = ajuste_manual, fator_proporcional
            valor_com_desconto = p.valor_bruto * (1 - p.desconto_total / 100)
            abono = p.funcionario.abono_valor if p.funcionario.abono_ativo else 0
            p.final_participacao = max(0, round(valor_com_desconto + abono * fator_proporcional + ajuste_manual, 2))
            p.save()
        messages.success(request, f"Ajustes para {trimestre} salvos.")
        return redirect('Participacao:configurar_ajustes_participacao')
    trimestres = sorted(set(p.trimestre for p in Participacao.objects.all()), reverse=True)
    selected_trimestre = request.GET.get('trimestre', '')
    participacoes = Participacao.objects.filter(trimestre=selected_trimestre) if selected_trimestre else []
    return render(request, 'Participacao/configurar_ajustes_participacao.html', {
        'trimestres': trimestres,
        'participacoes': participacoes,
        'selected_trimestre': selected_trimestre,
    })

@login_required
@gestor_required
@transaction.atomic
def configurar_abono_funcionario(request):
    funcionarios = Funcionario.objects.all()
    if request.method == 'POST':
        trimestre = request.POST.get('trimestre')
        if not trimestre:
            messages.error(request, "Selecione um trimestre.")
            return redirect('Participacao:configurar_abono_funcionario')
        participacoes = Participacao.objects.filter(trimestre=trimestre)
        today = date.today()
        if today > participacoes.first().data_pagamento or not participacoes.first().editavel:
            messages.error(request, f"Trimestre {trimestre} já pago ou aprovado.")
            return redirect('Participacao:configurar_abono_funcionario')
        for f in funcionarios:
            valor = float(request.POST.get(f'abono_{f.nome}', 0))
            tipo = request.POST.get(f'abono_type_{f.nome}', 'fixed')
            ativo = request.POST.get(f'abono_active_{f.nome}') == 'on'
            if valor < 0:
                messages.error(request, f"Valor do abono para {f.nome} não pode ser negativo.")
                continue
            f.abono_valor, f.abono_tipo, f.abono_ativo = valor, tipo, ativo
            f.save()
            if p := Participacao.objects.filter(funcionario=f, trimestre=trimestre).first():
                valor_bruto = float(f.setor.valor_base if f.setor else 0)
                abono = (valor_bruto * valor / 100) if tipo == 'percentage' else valor
                p.final_participacao = round(valor_bruto - (valor_bruto * p.desconto_total / 100) + (abono if ativo else 0), 2)
                p.save()
        messages.success(request, "Abonos atualizados.")
        return redirect('Participacao:configurar_abono_funcionario')
    trimestres = list(Participacao.objects.values_list('trimestre', flat=True).distinct())
    return render(request, 'participacao/configurar_abono_funcionario.html', {'funcionarios': funcionarios, 'trimestres': trimestres})

@login_required
@gestor_required
@transaction.atomic
def configurar_proporcional(request):
    if request.method == 'POST':
        if 'ignorar' in request.POST:
            logger.info("Ignorando funcionários com proporcional inválido.")
            funcionarios_invalidos = request.session.get('funcionarios_invalidos', [])
            for f in funcionarios_invalidos:
                p, _ = Participacao.objects.get_or_create(
                    funcionario_id=f['id'], trimester=f['trimestre'],
                    defaults={'data_pagamento': get_data_pagamento(f['trimestre']), 'editavel': True}
                )
                p.dias_trabalhados = 0
                p.save()
            del request.session['funcionarios_invalidos']
            params = request.session.get('recalcular_params', {})
            return redirect(f"{reverse('Participacao:recalcular_participacao')}?trimestre={params.get('trimestre', '')}")
        funcionarios_invalidos = request.session.get('funcionarios_invalidos', [])
        for f in funcionarios_invalidos:
            funcionario_id = f['id']
            proporcional = request.POST.get(f'proporcional_{funcionario_id}')
            dias_trabalhados = request.POST.get(f'dias_trabalhados_{funcionario_id}')
            try:
                funcionario = Funcionario.objects.get(id=funcionario_id)
                if proporcional:
                    proporcional = int(proporcional)
                    if 0 <= proporcional <= 90:
                        funcionario.proporcional = proporcional
                        funcionario.save()
                p, _ = Participacao.objects.get_or_create(
                    funcionario=funcionario, trimester=f['trimestre'],
                    defaults={'data_pagamento': get_data_pagamento(f['trimestre']), 'editavel': True}
                )
                if dias_trabalhados:
                    dias_trabalhados = int(dias_trabalhados)
                    if 0 <= dias_trabalhados <= 90:
                        p.dias_trabalhados = dias_trabalhados
                        p.dias_trabalhados_edited = True
                        p.save()
            except Exception as e:
                logger.error(f"Erro ao configurar {f['nome']}: {str(e)}")
                messages.error(request, f"Erro ao configurar {f['nome']}: {str(e)}")
        del request.session['funcionarios_invalidos']
        params = request.session.get('recalcular_params', {})
        return redirect(f"{reverse('Participacao:recalcular_participacao')}?trimestre={params.get('trimestre', '')}")
    funcionarios_invalidos = request.session.get('funcionarios_invalidos', [])
    if not funcionarios_invalidos:
        return redirect('Participacao:participacao')
    return render(request, 'participacao/configurar_proporcional.html', {'funcionarios': funcionarios_invalidos})

@login_required
@gestor_required
@transaction.atomic
def cadastrar_setor(request):
    is_master_admin = request.user.is_superuser
    if request.method == 'POST':
        nome = request.POST.get('nome')
        valor_base = request.POST.get('valor_base')
        if not nome or not valor_base:
            messages.error(request, "Nome e valor base são obrigatórios.")
            return redirect('Participacao:cadastrar_setor')
        try:
            valor_base = float(valor_base)
            if valor_base < 0:
                raise ValueError("Valor base não pode ser negativo.")
        except ValueError:
            messages.error(request, "Valor base deve ser um número válido e não negativo.")
            return redirect('Participacao:cadastrar_setor')
        try:
            setor = Setor.objects.create(nome=nome, valor_base=valor_base)
            if not is_master_admin:
                request.user.funcionario.setores_responsaveis.add(setor)
            logger.info(f"Setor '{nome}' cadastrado por {request.user.username}")
            messages.success(request, f"Setor '{nome}' cadastrado.")
        except Exception as e:
            logger.error(f"Erro ao cadastrar setor: {str(e)}")
            messages.error(request, f"Erro ao cadastrar setor: {str(e)}")
        return redirect('Participacao:participacao')
    return render(request, 'participacao/cadastrar_setor.html')