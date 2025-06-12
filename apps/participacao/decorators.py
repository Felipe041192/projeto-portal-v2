from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

def gestor_required(view_func):
    def wrapper(request, *args, **kwargs):
        logger.debug(f"Processando requisição para {request.path} - Usuário autenticado: {request.user.is_authenticated}")
        if not request.user.is_authenticated:
            messages.error(request, "Você precisa estar logado para acessar esta página.")
            return redirect('Participacao:login')
        try:
            funcionario = request.user.funcionario
        except AttributeError:
            logger.error(f"Usuário {request.user.username} não tem Funcionario associado.")
            messages.error(request, "Usuário não associado a funcionário. Contate o administrador.")
            return redirect('Participacao:login')
        if funcionario.tipo_acesso == 'gestor' or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        else:
            logger.warning(f"Usuário {request.user.username} (tipo: {funcionario.tipo_acesso}) tentou acessar página restrita.")
            messages.error(request, "Permissão negada.")
            return redirect('Participacao:login')
    return wrapper