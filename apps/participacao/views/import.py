from django.contrib import messages
from django.shortcuts import render, redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required
import logging
import pandas as pd
from django.core.exceptions import ObjectDoesNotExist
from ..models import Funcionario, Setor, Evento, Participacao, ValoresParticipacao
from ..services.calculos import get_trimestre, get_data_pagamento, recalcular_participacao

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

def converter_minutos(valor):
    if pd.isna(valor) or not str(valor).strip():
        return 0
    try:
        valor_str = str(valor).replace(',', '.')
        parts = valor_str.split('.')
        if len(parts) == 2 and len(parts[1]) <= 2:
            return int(float(valor_str) * 100)
        return int(float(valor_str) * 60)
    except (ValueError, TypeError):
        return 0

@login_required
@gestor_required
@transaction.atomic
def importar_planilha_participacao(request):
    logger.info("Iniciando importação de planilha")
    logger.debug(f"Método: {request.method}, FILES: {request.FILES}, POST: {request.POST}")
    trimestres_disponiveis = ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]

    if request.method == 'GET':
        return render(request, 'participacao/importar_planilha.html', {'trimestres': trimestres_disponiveis})

    if request.method != 'POST':
        logger.info("Requisição não é POST, redirecionando")
        return redirect('Participacao:participacao')

    file = request.FILES.get('file') or request.FILES.get('arquivo')
    if not file:
        logger.error("Nenhum arquivo encontrado")
        messages.error(request, "Selecione um arquivo (.csv, .xlsx ou .xls).")
        return redirect('Participacao:participacao')

    logger.info(f"Arquivo recebido: {file.name}")
    trimestre_selecionado = request.POST.get('trimestre')
    if trimestre_selecionado and trimestre_selecionado not in trimestres_disponiveis:
        logger.error(f"Trimestre inválido: {trimestre_selecionado}")
        messages.error(request, "Trimestre inválido.")
        return redirect('Participacao:participacao')

    try:
        if file.name.endswith('.csv'):
            dtypes = {2: str, 5: str, 8: str, 38: str, 41: str, 46: str}
            df = pd.read_csv(file, encoding='utf-8', delimiter=';', header=4, dtype=dtypes, low_memory=False)
        else:
            df = pd.read_excel(file, skiprows=5)
        logger.info(f"Planilha lida: {len(df)} linhas")
    except pd.errors.ParserError as e:
        logger.error(f"Erro CSV: {str(e)}")
        messages.error(request, "Erro: CSV malformado ou delimitador incorreto.")
        return redirect('Participacao:participacao')
    except Exception as e:
        logger.error(f"Erro ao ler planilha: {str(e)}")
        messages.error(request, f"Erro ao ler planilha: {str(e)}")
        return redirect('Participacao:participacao')

    if df.shape[1] < 47:
        logger.error("Colunas insuficientes")
        messages.error(request, "Planilha com colunas insuficientes (mínimo 47).")
        return redirect('Participacao:participacao')

    df['Data'] = pd.to_datetime(df.iloc[:, 2].astype(str).str.strip().replace("nan", pd.NA).ffill(), format='%d/%m/%Y', errors='coerce')
    df['Dia'] = df.iloc[:, 5].astype(str).replace("nan", pd.NA).ffill()
    df['Funcionario'] = df.iloc[:, 8].astype(str).replace("nan", pd.NA).ffill()
    df['Evento'] = df.iloc[:, 41].astype(str).replace("nan", pd.NA)
    df['Codigo_Evento'] = df.iloc[:, 38].astype(str).replace("nan", pd.NA)
    df['Horas_Minutos'] = df.iloc[:, 46].astype(str).replace("nan", pd.NA)
    df['Minutos'] = df['Horas_Minutos'].apply(converter_minutos)

    logger.debug("Amostra de datas: %s", df['Data'].head(10).to_string())
    logger.debug("Amostra de funcionários: %s", df['Funcionario'].head(10).to_string())

    all_employees = df['Funcionario'].dropna().unique()
    existing_employees = set(Funcionario.objects.values_list('nome', flat=True))
    missing_funcionarios = [emp for emp in all_employees if emp not in existing_employees and emp.lower() != "nome funcionário"]
    logger.debug(f"Todos: {list(all_employees)}, Existentes: {list(existing_employees)}, Missing: {missing_funcionarios}")

    if missing_funcionarios:
        logger.warning(f"Funcionários não encontrados: {missing_funcionarios}")
        request.session['missing_funcionarios'] = [str(emp)[:50] for emp in missing_funcionarios]
        df['Data'] = df['Data'].dt.strftime('%Y-%m-%d')
        request.session['planilha_data'] = df.to_json(date_format='iso')
        request.session['trimestre_selecionado'] = trimestre_selecionado
        return redirect('Participacao:confirmar_cadastro_funcionarios')

    logger.info("Todos funcionários encontrados, prosseguindo")
    return processar_importacao_planilha(request, df, trimestre_selecionado=trimestre_selecionado)

@login_required
@gestor_required
@transaction.atomic
def confirmar_cadastro_funcionarios(request):
    if request.method == 'POST':
        missing_funcionarios = request.session.get('missing_funcionarios', [])
        planilha_data = request.session.get('planilha_data', None)
        trimestre_selecionado = request.session.get('trimestre_selecionado', None)
        if not missing_funcionarios or not planilha_data:
            messages.error(request, "Dados da sessão ausentes. Reimporte a planilha.")
            return redirect('Participacao:participacao')
        if 'confirmar' in request.POST:
            try:
                with transaction.atomic():
                    for nome in missing_funcionarios:
                        data_admissao_str = request.POST.get(f'data_admissao_{nome}', '').strip()
                        proporcional_str = request.POST.get(f'proporcional_{nome}', '0').strip()
                        setor_id = request.POST.get(f'setor_{nome}', '').strip()
                        if not data_admissao_str or not setor_id:
                            messages.error(request, f"Dados obrigatórios ausentes para {nome}.")
                            return render(request, 'participacao/confirmar_cadastro_funcionarios.html', {
                                'missing_funcionarios': missing_funcionarios,
                                'setores': Setor.objects.all()
                            })
                        data_admissao = pd.to_datetime(data_admissao_str, format='%d/%m/%Y').date()
                        if data_admissao > date.today():
                            messages.error(request, f"Data futura para {nome}.")
                            return render(request, 'participacao/confirmar_cadastro_funcionarios.html', {
                                'missing_funcionarios': missing_funcionarios,
                                'setores': Setor.objects.all()
                            })
                        proporcional = int(proporcional_str)
                        if proporcional < 0 or proporcional > 90:
                            messages.error(request, f"Proporcional inválido para {nome}.")
                            return render(request, 'participacao/confirmar_cadastro_funcionarios.html', {
                                'missing_funcionarios': missing_funcionarios,
                                'setores': Setor.objects.all()
                            })
                        setor = Setor.objects.get(id=setor_id)
                        username = nome.lower().replace(' ', '_')
                        if User.objects.filter(username=username).exists():
                            username += f"_{User.objects.count() + 1}"
                        user = User.objects.create_user(username=username, password='default_password')
                        Funcionario.objects.create(
                            usuario=user, nome=nome, setor=setor, data_admissao=data_admissao,
                            proporcional=proporcional, tipo_participacao='proporcional'
                        )
                    messages.success(request, "Funcionários cadastrados.")
                    df = pd.read_json(planilha_data)
                    df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
                    request.session.pop('missing_funcionarios')
                    request.session.pop('planilha_data')
                    response = processar_importacao_planilha(request, df, trimestre_selecionado=trimestre_selecionado)
                    if trimestre_selecionado:
                        request.GET = request.GET.copy()
                        request.GET['trimestre'] = trimestre_selecionado
                        recalcular_participacao(request)
                    request.session.pop('trimestre_selecionado')
                    return response
            except Exception as e:
                logger.error(f"Erro ao cadastrar: {str(e)}")
                messages.error(request, f"Erro ao cadastrar: {str(e)}")
                return redirect('Participacao:participacao')
        messages.info(request, "Importação cancelada.")
        request.session.pop('missing_funcionarios')
        request.session.pop('planilha_data')
        request.session.pop('trimestre_selecionado')
        return redirect('Participacao:participacao')
    missing_funcionarios = request.session.get('missing_funcionarios', [])
    return render(request, 'participacao/confirmar_cadastro_funcionarios.html', {
        'missing_funcionarios': missing_funcionarios,
        'setores': Setor.objects.all()
    })

@login_required
@gestor_required
@transaction.atomic
def processar_importacao_planilha(request, df, trimestre_selecionado=None):
    logger.info("Prosseguindo com a importação da planilha")
    linhas_processadas = 0
    linhas_ignoradas = 0
    df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
    logger.debug("Amostra de datas: %s", df['Data'].head(10).apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'NaT').to_string())
    trimestres = set(get_trimestre(data) for data in df['Data'].dropna() if not pd.isna(data))
    logger.debug(f"Trimestres identificados: {trimestres}")
    trimestre_atual = trimestre_selecionado if trimestre_selecionado else max(trimestres) if trimestres else None
    if not trimestre_atual or trimestre_atual not in ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]:
        logger.error("Trimestre inválido ou não identificado")
        messages.error(request, "Trimestre inválido ou não identificado na planilha.")
        return redirect('Participacao:participacao')
    try:
        valores = ValoresParticipacao.objects.get(trimestre=trimestre_atual)
        logger.info(f"Valores carregados: Doc Normais={valores.documentos_normais}, Dedução Normal={valores.deducao_normal}")
    except ValoresParticipacao.DoesNotExist:
        logger.error(f"Valores não configurados para {trimestre_atual}")
        messages.error(request, f"Configure os valores para {trimestre_atual} antes de importar.")
        return redirect('Participacao:configurar_participacao_setor')
    logger.debug(f"Limpando eventos e participações para {trimestre_atual}")
    Evento.objects.filter(trimestre=trimestre_atual, is_manual=False).delete()
    Participacao.objects.filter(trimestre=trimestre_atual).delete()
    logger.info(f"Dados de {trimestre_atual} deletados")
    setor_padrao, _ = Setor.objects.get_or_create(nome="Não informado", defaults={'valor_base': 0})
    mask_penalidades = df['Evento'].str.contains(
        "horas atraso|saídas antecipadas|atestado|falta justificada|falta não justificada|falta parcial|falta total|esquecimento|compensado|advertência|licença maternidade",
        na=False, case=False
    ) | df['Codigo_Evento'].isin(['23', '26', '14', '3', 'esq', 'comp', '16'])
    df_eventos = df.loc[mask_penalidades, ['Funcionario', 'Data', 'Dia', 'Evento', 'Codigo_Evento', 'Horas_Minutos', 'Minutos']].dropna(subset=["Data", "Funcionario"])
    logger.debug("Amostra de eventos: %s", df_eventos[['Evento', 'Codigo_Evento', 'Minutos']].head(10).to_string())
    mask_horas_normais = df['Evento'].str.contains("horas normais", na=False, case=False) | df['Codigo_Evento'].isin(['1'])
    df_horas_normais = df.loc[mask_horas_normais, ['Funcionario', 'Data']].dropna(subset=["Data", "Funcionario"])
    dias_trabalhados_por_funcionario = {nome: set() for nome in df['Funcionario'].dropna().unique()}
    for _, row in df_horas_normals.iterrows():
        nome = row["Funcionario"][:50]
        data = row["Data"]
        if pd.notna(data):
            data_dt = pd.to_datetime(data).date()
            trimestre_evento = get_trimestre(data_dt)
            if trimestre_evento == trimestre_atual:
                dias_trabalhados_por_funcionario[nome].add(data_dt.strftime('%Y-%m-%d'))
    for _, row in df_eventos.iterrows():
        nome = row["Funcionario"][:50]
        data = row["Data"]
        evento = str(row['Evento']).lower()
        if pd.notna(data):
            data_dt = pd.to_datetime(data).date()
            trimestre_evento = get_trimestre(data_dt)
            if trimestre_evento == trimestre_atual and "licença maternidade" in evento:
                data_str = data_dt.strftime('%Y-%m-%d')
                if data_str in dias_trabalhados_por_funcionario[nome]:
                    dias_trabalhados_por_funcionario[nome].remove(data_str)
    df_eventos = df_eventos.groupby(['Funcionario', 'Data', 'Evento']).first().reset_index()
    for idx, row in df_eventos.iterrows():
        nome = row["Funcionario"][:50]
        data = row["Data"]
        minutos = row["Minutos"]
        dia = row["Dia"]
        evento = row["Evento"]
        logger.debug(f"Processando linha {idx + 1}: {nome}, {evento}, {data}, {minutos}")
        if pd.isna(data):
            logger.warning(f"Linha {idx + 1} ignorada: Data nula")
            linhas_ignoradas += 1
            continue
        data_dt = pd.to_datetime(data).date()
        if data_dt.year < 2000:
            logger.warning(f"Linha {idx + 1} ignorada: Data inválida")
            linhas_ignoradas += 1
            continue
        mes_ano = data_dt.strftime('%Y-%m')
        mes_ano_display = data_dt.strftime('%B %Y').capitalize()
        trimestre = get_trimestre(data_dt)
        if trimestre != trimestre_atual:
            logger.debug(f"Linha {idx + 1} ignorada: Trimestre diferente")
            continue
        funcionario = Funcionario.objects.filter(nome=nome).first()
        if not funcionario or not funcionario.setor or not funcionario.setor.recebe_participacao:
            logger.warning(f"Linha {idx + 1} ignorada: Funcionário {nome} inválido")
            linhas_ignoradas += 1
            continue
        if not funcionario.setor:
            logger.warning(f"Associando {nome} a 'Não informado'")
            funcionario.setor = setor_padrao
            funcionario.save()
        Evento.objects.create(
            funcionario=funcionario,
            tipo=evento,
            data=data_dt,
            dia=dia,
            minutos=minutos,
            horas_minutos=row["Horas_Minutos"] if not pd.isna(row["Horas_Minutos"]) else "-",
            status="-",
            mes_ano=mes_ano,
            mes_ano_display=mes_ano_display,
            trimestre=trimestre,
            is_manual=False
        )
        linhas_processadas += 1
    for funcionario in Funcionario.objects.filter(setor__recebe_participacao=True):
        dias = len(dias_trabalhados_por_funcionario.get(funcionario.nome, set()))
        Participacao.objects.update_or_create(
            funcionario=funcionario,
            trimestre=trimestre_atual,
            defaults={'data_pagamento': get_data_pagamento(trimestre_atual), 'editavel': True, 'dias_trabalhados': dias}
        )
    logger.info(f"Importação concluída: {linhas_processadas} processadas, {linhas_ignoradas} ignoradas")
    messages.success(request, f"Planilha processada. {linhas_processadas} linhas processadas, {linhas_ignoradas} ignoradas.")
    request.GET = request.GET.copy()
    request.GET['trimestre'] = trimestre_atual
    recalcular_participacao(request)
    return redirect('Participacao:participacao')