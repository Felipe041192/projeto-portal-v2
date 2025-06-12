# apps/participacao/views/__init__.py
from .auth import login, logout_view
from .reports import (
    detalhes_calculo_participacao,
    gerar_relatorio_pdf,
    gerar_relatorio_excel,
    download_extrato_pdf,
    download_relatorio_pagamento
)
from .participation import (
    index,
    participacao,
    editar_dias_trabalhados,
    recalcular_participacao,
    configurar_participacao_setor,
    configurar_regras_participacao,
    configurar_setores_participacao,
    cadastrar_setor,
    cadastrar_funcionario,
    funcionarios,
    editar_funcionario,
    alternar_abono,
    inserir_eventos,
    listar_eventos,
    importar_planilha_participacao,
    configurar_proporcional,
    configurar_ajustes_participacao,
    calcular_participacao,
    revogar_aprovacao_participacao,
    recalcular_funcionario,
    adicionar_advertencia,
    aprovar_participacao,
    extrato,
    download_extrato_pdf,
    logs_geral,
    logs,
    configurar_abono_funcionario
)

__all__ = [
    'login', 'logout_view',
    'index', 'participacao', 'editar_dias_trabalhados', 'recalcular_participacao',
    'configurar_participacao_setor', 'configurar_regras_participacao',
    'configurar_setores_participacao', 'cadastrar_setor', 'cadastrar_funcionario',
    'funcionarios', 'editar_funcionario', 'alternar_abono', 'inserir_eventos',
    'listar_eventos', 'importar_planilha_participacao', 'configurar_proporcional',
    'configurar_ajustes_participacao', 'calcular_participacao',
    'revogar_aprovacao_participacao', 'recalcular_funcionario', 'adicionar_advertencia',
    'aprovar_participacao', 'detalhes_calculo_participacao', 'gerar_relatorio_pdf',
    'gerar_relatorio_excel', 'download_extrato_pdf', 'download_relatorio_pagamento',
    'extrato', 'logs_geral', 'logs', 'configurar_abono_funcionario'
]