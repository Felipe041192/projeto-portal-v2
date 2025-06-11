def get_trimestre(data):
    """Calcula o trimestre com base na data fornecida. Ex.: 2025-05-02 -> 2025-Q2"""
    ano = data.year
    mes = data.month
    if 1 <= mes <= 3:
        return f"{ano}-Q1"
    elif 4 <= mes <= 6:
        return f"{ano}-Q2"
    elif 7 <= mes <= 9:
        return f"{ano}-Q3"
    else:
        return f"{ano}-Q4"

def get_trimestre_from_date(data):
    """Retorna o trimestre no formato YYYY-QN para uma data."""
    if not data:
        return None
    year = data.year
    month = data.month
    quarter = (month - 1) // 3 + 1
    return f"{year}-Q{quarter}"

def get_data_pagamento(trimestre):
    """Retorna a data de pagamento para o trimestre."""
    ano, q = map(int, trimestre.split('-Q'))
    if q == 1:
        return pd.Timestamp(f"{ano}-04-15").date()
    elif q == 2:
        return pd.Timestamp(f"{ano}-07-15").date()
    elif q == 3:
        return pd.Timestamp(f"{ano}-10-15").date()
    else:
        return pd.Timestamp(f"{ano+1}-01-15").date()

def get_regra_valida(indicador, data):
    """
    Retorna a regra válida para um indicador em uma data específica.
    Busca no banco ou usa valores padrão se não houver regra personalizada.
    """
    logger.debug(f"Buscando regra para {indicador} na data {data}")
    regras = RegraParticipacao.objects.filter(
        Q(indicador__iexact=indicador) &
        Q(data_inicio__lte=data) &
        (Q(data_fim__gte=data) | Q(data_fim__isnull=True))
    ).order_by('-data_inicio')
    if regras.exists():
        regra = regras.first()
        logger.debug(f"Regra encontrada: {regra.indicador}, Tolerância={regra.tolerancia}, Representatividade={regra.representatividade}")
        return regra
    logger.debug(f"Nenhuma regra personalizada para {indicador}. Usando padrão nulo.")
    return None

def calcular_penalidades(emp_data, valor_bruto, data_evento):
    """Calcula as penalidades para um funcionário com base nos eventos e regras dinâmicas."""
    logger.debug(f"Calculando penalidades para data_evento={data_evento}")
    desconto_total = 0.0
    penalidades_totais = 0.0
    detalhes_descontos = []
    eventos = emp_data["eventos"]
    if not eventos:
        logger.debug("Nenhum evento para calcular penalidades")
        return (0.0, 0.0, [], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    eventos_por_periodo = defaultdict(lambda: defaultdict(int))
    for evento in eventos:
        data = pd.to_datetime(evento["data"], format='%d/%m/%Y').date()
        mes_ano = data.strftime('%Y-%m') if get_regra_valida(evento["tipo"], data).periodo == 'mensal' else get_trimestre(data)
        eventos_por_periodo[mes_ano][evento["tipo"]] += 1

    for indicador, count_dict in eventos_por_periodo.items():
        regra = get_regra_valida(indicador, data_evento)
        if not regra:
            logger.warning(f"Sem regra para {indicador} em {data_evento}")
            continue
        total_ocorrencias = sum(count_dict.values())
        if total_ocorrencias <= regra.tolerancia:
            continue
        excedente = total_ocorrencias - regra.tolerancia
        penalidade_base = regra.representatividade * excedente
        penalidade_adicional = regra.valor_subsequente * (excedente - 1) if excedente > 1 else 0.0
        penalidade_total = penalidade_base + penalidade_adicional
        desconto_total += penalidade_total
        penalidade_valor = (valor_bruto * penalidade_total / 100) if valor_bruto > 0 else 0.0
        penalidades_totais += penalidade_valor
        detalhes_descontos.append({
            "motivo": f"{indicador} ({total_ocorrencias} eventos, tolerância {regra.tolerancia})",
            "valor": round(penalidade_valor, 2)
        })
        logger.info(f"Penalidade para {indicador}: {penalidade_total}% (Base={penalidade_base}%, Adicional={penalidade_adicional}%)")

    # Ajuste específico para licença maternidade (agora configurável)
    licenca_regra = get_regra_valida("licenca_maternidade", data_evento)
    if licenca_regra and emp_data["licenca_maternidade_count"] > 0:
        penalidade_licenca = licenca_regra.representatividade  # Configurável via interface
        desconto_total += penalidade_licenca
        penalidade_valor = (valor_bruto * penalidade_licenca / 100) if valor_bruto > 0 else 0.0
        penalidades_totais += penalidade_valor
        detalhes_descontos.append({
            "motivo": f"Licença Maternidade ({emp_data['licenca_maternidade_count']} eventos)",
            "valor": round(penalidade_valor, 2)
        })
        logger.info(f"Penalidade Licença Maternidade: {penalidade_licenca}%")

    desconto_total = min(desconto_total, 100.0)
    return (
        desconto_total, penalidades_totais, detalhes_descontos,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0  # Placeholders, a serem refinados por indicador
    )

def recalcular_participacao_funcionario(funcionario, trimester):
    try:
        participacao = Participacao.objects.get(funcionario=funcionario, trimester=trimestre)
    except Participacao.DoesNotExist:
        logger.error(f"Participação não encontrada para {funcionario.nome} em {trimestre}")
        return
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
    eventos = Evento.objects.filter(funcionario=funcionario, trimester=trimestre)
    logger.debug(f"Eventos para {funcionario.nome} em {trimestre}: {eventos.count()}")
    for evento in eventos:
        mes_ano_display = evento.mes_ano_display
        grouped["eventos"].append({
            "tipo": evento.type, "data": evento.data.strftime('%d/%m/%Y'), "mes_ano": evento.mes_ano,
            "mes_ano_display": mes_ano_display, "dia": evento.dia, "minutos": evento.minutos,
            "status": evento.status, "horas_minutos": evento.horas_minutos, "compensado": getattr(evento, 'compensado', False)
        })
        grouped["datas_trabalhadas"].add(evento.data.strftime('%Y-%m-%d'))
        if evento.type == "atraso" and not getattr(evento, 'compensado', False) and evento.minutos >= 5:
            grouped["atraso_count"] += 1
            if 5 <= evento.minutos <= 10:
                grouped["atraso_by_month"][mes_ano_display] += 1
            elif evento.minutos > 10 and evento.minutos <= 240:
                grouped["falta_meio_turno_count"] += 1
                grouped["falta_meio_turno_by_month"][mes_ano_display] += 1
            elif evento.minutos > 240:
                grouped["falta_dia_todo_count"] += 1
                grouped["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "saida_antecipada" and not getattr(evento, 'compensado', False) and evento.minutos >= 5:
            grouped["saida_antecipada_count"] += 1
            if 5 <= evento.minutos <= 10:
                grouped["saida_antecipada_by_month"][mes_ano_display] += 1
            elif evento.minutos > 10 and evento.minutos <= 240:
                grouped["falta_meio_turno_count"] += 1
                grouped["falta_meio_turno_by_month"][mes_ano_display] += 1
            elif evento.minutos > 240:
                grouped["falta_dia_todo_count"] += 1
                grouped["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "atestado":
            grouped["atestado_count"] += 1
        elif evento.type == "falta_justificada":
            grouped["falta_justificada_count"] += 1
            grouped["datas_faltas"].add(evento.data.strftime('%Y-%m-%d'))
        elif evento.type == "falta_nao_justificada":
            grouped["falta_nao_justificada_count"] += 1
            grouped["datas_faltas"].add(evento.data.strftime('%Y-%m-%d'))
        elif evento.type == "falta_meio_turno":
            grouped["falta_meio_turno_count"] += 1
            grouped["falta_meio_turno_by_month"][mes_ano_display] += 1
        elif evento.type == "falta_dia_todo":
            grouped["falta_dia_todo_count"] += 1
            grouped["falta_dia_todo_by_month"][mes_ano_display] += 1
        elif evento.type == "esquecimento_ponto":
            grouped["esquecimento_ponto_count"] += 1
            grouped["esquecimento_ponto_by_month"][mes_ano_display] += 1
        elif evento.type == "advertencia":
            grouped["advertencia_count"] += 1
            grouped["advertencia_by_month"][mes_ano_display] += 1
        elif evento.type == "compensacao":
            grouped["compensacao_count"] += 1
        elif evento.type == "licenca_maternidade":
            grouped["licenca_maternidade_count"] += 1
    data_evento = min(e.data for e in eventos) if eventos else date.today()
    desconto_total, penalidades_totais, detalhes_descontos, _, _, _, _, _, _, _, _, _, _ = calcular_penalidades(grouped, participacao.valor_bruto, data_evento)
    valor_liquido = participacao.valor_bruto * (1 - desconto_total / 100)
    percentual = float(funcionario.percentual_participacao)
    if percentual < 100:
        valor_antes = valor_liquido
        valor_liquido *= (percentual / 100)
        detalhes_descontos.append({"motivo": f"Percentual {percentual}%", "value": round(valor_antes - valor_liquido, 2)})
    if funcionario.type_participation == 'proporcional' and participacao.dias_trabalhados < 90:
        valor_antes = valor_liquido
        valor_liquido = (participacao.valor_bruto / 90) * participacao.dias_trabalhados
        desconto = valor_antes - valor_liquido
        detalhes_descontos.append({"motivo": f"Proporcional {participacao.dias_trabalhados} dias", "value": round(desconto, 2)})
    if funcionario.abono_ativo:
        valor_antes = valor_liquido
        abono = (participacao.valor_bruto * float(funcionario.abono_valor) / 100) if funcionario.abono_type == "percentage" else float(funcionario.abono_valor)
        valor_liquido += abono
        detalhes_descontos.append({"motivo": f"Abono {funcionario.abono_type} {funcionario.abono_valor}", "value": -round(abono, 2)})
    valor_liquido += float(participacao.ajuste_manual)
    valor_liquido = max(0, round(valor_liquido, 0))
    participacao.atraso_count = grouped["atraso_count"]
    participacao.saida_antecipada_count = grouped["saida_antecipada_count"]
    participacao.atestado_count = grouped["atestado_count"]
    participacao.falta_justificada_count = grouped["falta_justificada_count"]
    participacao.falta_nao_justificada_count = grouped["falta_nao_justificada_count"]
    participacao.falta_meio_turno_count = grouped["falta_meio_turno_count"]
    participacao.falta_dia_todo_count = grouped["falta_dia_todo_count"]
    participacao.esquecimento_ponto_count = grouped["esquecimento_ponto_count"]
    participacao.compensacao_count = grouped["compensacao_count"]
    participacao.advertencia_count = grouped["advertencia_count"]
    participacao.licenca_maternidade_count = grouped["licenca_maternidade_count"]
    participacao.desconto_total = desconto_total / 100
    participacao.penalidades_totais = penalidades_totais / 100
    participacao.final_participation = valor_liquido
    participacao.detalhes_descontos = detalhes_descontos
    participacao.atraso_by_month = dict(grouped["atraso_by_month"])
    participacao.saida_antecipada_by_month = dict(grouped["saida_antecipada_by_month"])
    participacao.save()
    logger.info(f"Participação recalculada para {funcionario.nome} em {trimestre}")