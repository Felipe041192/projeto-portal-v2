# apps/participacao/views/main_views.py
from django.shortcuts import render

def index(request):
    return render(request, 'participacao/index.html')

def participacao(request):
    return render(request, 'participacao/participacao.html')

def configurar_participacao_setor(request):
    return render(request, 'participacao/configurar_participacao_setor.html')

def configurar_regras_participacao(request):
    return render(request, 'participacao/configurar_regras_participacao.html')

def configurar_setores_participacao(request):
    return render(request, 'participacao/configurar_setores_participacao.html')

def cadastrar_setor(request):
    return render(request, 'participacao/cadastrar_setor.html')

def cadastrar_funcionario(request):
    return render(request, 'participacao/cadastrar_funcionario.html')

def funcionarios(request):
    return render(request, 'participacao/funcionarios.html')

def editar_funcionario(request, pk):
    return render(request, 'participacao/editar_funcionario.html')

def alternar_abono(request):
    return render(request, 'participacao/participacao.html')  # Ajuste conforme necessário

def recalcular_participacao(request):
    return render(request, 'participacao/recalcular_participacao.html')

def inserir_eventos(request):
    return render(request, 'participacao/participacao.html')  # Ajuste conforme necessário

def listar_eventos(request, funcionario_id):
    return render(request, 'participacao/participacao.html')  # Ajuste conforme necessário

def editar_dias_trabalhados(request, pk):
    return render(request, 'participacao/participacao.html')  # Ajuste conforme necessário

def importar_planilha_participacao(request):
    return render(request, 'participacao/importar_planilha_participacao.html')