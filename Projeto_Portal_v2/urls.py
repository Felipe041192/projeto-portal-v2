from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

def redirect_to_login(request):
    return redirect('Participacao:login')  # Redireciona para a URL de login do app participacao

urlpatterns = [
    path('', redirect_to_login),  # Rota para a URL raiz
    path('admin/', admin.site.urls),
    path('participacao/', include('apps.participacao.urls', namespace='Participacao')),
]