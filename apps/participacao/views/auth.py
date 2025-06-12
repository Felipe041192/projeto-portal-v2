from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.auth.models import User
import logging
import os
from django.core.exceptions import ObjectDoesNotExist
from ..models import LoginAttempt, UserActionLog, Funcionario  # Import relativo

logger = logging.getLogger(__name__)

# Criar diretório logs se não existir
log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'participacao.log')),
        logging.StreamHandler()
    ]
)

def gestor_required(view_func):
    def wrapper(request, *args, **kwargs):
        logger.debug(f"Processando requisição para {request.path} - Usuário autenticado: {request.user.is_authenticated}")
        if not request.user.is_authenticated:
            messages.error(request, "Você precisa estar logado para acessar esta página.")
            return redirect('Participacao:login')
        try:
            funcionario = request.user.funcionario
        except Funcionario.DoesNotExist:
            logger.error(f"Usuário {request.user.username} não tem um Funcionario associado.")
            messages.error(request, "Seu usuário não está associado a um funcionário. Contate o administrador.")
            return redirect('Participacao:login')
        if funcionario.tipo_acesso == 'gestor' or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        else:
            logger.warning(f"Usuário {request.user.username} (tipo: {funcionario.tipo_acesso}) tentou acessar uma página restrita a gestores.")
            messages.error(request, "Você não tem permissão para acessar esta página.")
            return redirect('Participacao:login')
    return wrapper

def login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
        is_malicious = False
        try:
            user = User.objects.filter(username=username).first()
            if user:
                try:
                    funcionario = user.funcionario
                    if user.is_superuser or (funcionario and funcionario.tipo_acesso in ['gestor', 'master_admin']):
                        if request.user.is_authenticated and not (request.user.is_superuser or request.user.funcionario.tipo_acesso in ['gestor', 'master_admin']):
                            is_malicious = True
                        else:
                            is_malicious = True  # Revisar lógica se necessário
                except AttributeError:
                    pass
            LoginAttempt.objects.create(
                username_attempted=username,
                ip_address=ip_address,
                is_malicious=is_malicious,
                user=request.user if request.user.is_authenticated else None
            )
            logger.info(f"Registrada tentativa de login: username={username}, IP={ip_address}, Maliciosa={is_malicious}")
        except Exception as e:
            logger.error(f"Erro ao registrar tentativa de login: {str(e)}")
        user = authenticate(request, username=username, password=password)
        if user:
            auth_login(request, user)
            messages.success(request, "Login realizado com sucesso!")
            return redirect('Participacao:index')
        messages.error(request, "Usuário ou senha incorretos.")
        logger.warning(f"Falha na tentativa de login: username={username}, IP={ip_address}")
    return render(request, 'participacao/login.html', {})

def logout_view(request):
    logger.info(f"Usuário {request.user.username if request.user.is_authenticated else 'anônimo'} está fazendo logout. Método: {request.method}")
    if request.method == 'POST':
        logout(request)
        request.session.flush()
        response = redirect('Participacao:login')
        response.delete_cookie('sessionid')
        messages.success(request, "Você saiu da sessão.")
        return response
    logger.warning("Tentativa de logout com método GET, redirecionando para login")
    return redirect('Participacao:login')