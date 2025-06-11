from django.urls import path
from .views.auth import login, logout_view
from .views.main_views import (  # Substitua 'main_views' por 'views' se não renomear
    index,
    participacao,
    configurar_participacao_setor,
    configurar_regras_participacao,
    configurar_setores_participacao,
    cadastrar_setor,
    cadastrar_funcionario,
    funcionarios,
    editar_funcionario,
    alternar_abono,
    recalcular_participacao,
    inserir_eventos,
    listar_eventos,
    editar_dias_trabalhados,
    importar_planilha_participacao
)
from .views.reports import (
    detalhes_calculo_participacao,
    gerar_relatorio_pdf,
    gerar_relatorio_excel,
    download_extrato_pdf,
    download_relatorio_pagamento
)

app_name = 'Participacao'

urlpatterns = [
    # Autenticação
    path('login/', login, name='login'),
    path('logout/', logout_view, name='logout'),

    # Painel Principal
    path('', index, name='index'),
    path('participacao/', participacao, name='participacao'),

    # Configurações
    path('configurar_participacao_setor/', configurar_participacao_setor, name='configurar_participacao_setor'),
    path('configurar_regras_participacao/', configurar_regras_participacao, name='configurar_regras_participacao'),
    path('configurar_setores_participacao/', configurar_setores_participacao, name='configurar_setores_participacao'),

    # Funcionários e Setores
    path('cadastrar_setor/', cadastrar_setor, name='cadastrar_setor'),
    path('cadastrar_funcionario/', cadastrar_funcionario, name='cadastrar_funcionario'),
    path('funcionarios/', funcionarios, name='funcionarios'),
    path('editar_funcionario/<int:pk>/', editar_funcionario, name='editar_funcionario'),
    path('alternar_abono/', alternar_abono, name='alternar_abono'),

    # Participação
    path('recalcular_participacao/', recalcular_participacao, name='recalcular_participacao'),
    path('detalhes_calculo_participacao/', detalhes_calculo_participacao, name='detalhes_calculo_participacao'),
    path('extrato/<str:funcionario_nome>/', download_extrato_pdf, name='extrato'),
    path('inserir_eventos/', inserir_eventos, name='inserir_eventos'),
    path('listar_eventos/<int:funcionario_id>/', listar_eventos, name='listar_eventos'),
    path('editar_dias_trabalhados/<int:pk>/', editar_dias_trabalhados, name='editar_dias_trabalhados'),

    # Importação
    path('importar_planilha_participacao/', importar_planilha_participacao, name='importar_planilha_participacao'),

    # Relatórios
    path('gerar_relatorio_pdf/', gerar_relatorio_pdf, name='gerar_relatorio_pdf'),
    path('gerar_relatorio_excel/', gerar_relatorio_excel, name='gerar_relatorio_excel'),
    path('download_relatorio_pagamento/', download_relatorio_pagamento, name='download_relatorio_pagamento'),
]