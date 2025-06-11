# Importa funções de diferentes arquivos dentro de views/
from .auth import login, logout_view
from .views import index, participacao, configurar_participacao_setor, configurar_regras_participacao
from .views import configurar_setores_participacao, cadastrar_setor, cadastrar_funcionario
from .views import funcionarios, editar_funcionario, alternar_abono, recalcular_participacao
from .reports import detalhes_calculo_participacao, gerar_relatorio_pdf, gerar_relatorio_excel
from .reports import download_extrato_pdf, download_relatorio_pagamento
from .views import inserir_eventos, listar_eventos, editar_dias_trabalhados
from .views import importar_planilha_participacao

# Define explicitamente quais funções estão disponíveis para importação
__all__ = [
    'login', 'logout_view', 'index', 'participacao', 'configurar_participacao_setor',
    'configurar_regras_participacao', 'configurar_setores_participacao', 'cadastrar_setor',
    'cadastrar_funcionario', 'funcionarios', 'editar_funcionario', 'alternar_abono',
    'recalcular_participacao', 'detalhes_calculo_participacao', 'gerar_relatorio_pdf',
    'gerar_relatorio_excel', 'download_extrato_pdf', 'download_relatorio_pagamento',
    'inserir_eventos', 'listar_eventos', 'editar_dias_trabalhados', 'importar_planilha_participacao'
]