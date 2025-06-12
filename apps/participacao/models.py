from django.db import models

def get_user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()

class Setor(models.Model):
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Setor")
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Base")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    recebe_participacao = models.BooleanField(default=False, verbose_name="Recebe Participação")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"

class Funcionario(models.Model):
    usuario = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, verbose_name="Usuário")
    nome = models.CharField(max_length=100, verbose_name="Nome")
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Setor")
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, null=True, blank=True, related_name='funcionarios')
    data_admissao = models.DateField(null=True, blank=True, verbose_name="Data de Admissão")
    data_demissao = models.DateField(null=True, blank=True, verbose_name="Data de Demissão")
    tipo_acesso = models.CharField(max_length=20, choices=[('gestor', 'Gestor'), ('master_admin', 'Master Admin')], default='gestor', verbose_name="Tipo de Acesso")
    tipo_participacao = models.CharField(max_length=20, choices=[('normal', 'Normal'), ('proporcional', 'Proporcional'), ('menor_aprendiz', 'Menor Aprendiz')], default='normal', verbose_name="Tipo de Participação")
    percentual_participacao = models.DecimalField(max_digits=5, decimal_places=2, default=100.00, verbose_name="Percentual de Participação (%)")
    proporcional = models.IntegerField(default=0, verbose_name="Dias Proporcionais")
    trimestre_inicio_participacao = models.CharField(max_length=10, null=True, blank=True, verbose_name="Trimestre de Início")
    abono_ativo = models.BooleanField(default=False, verbose_name="Abono Ativo")
    abono_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor do Abono")
    abono_type = models.CharField(max_length=10, choices=[('fixed', 'Fixo'), ('percentage', 'Percentual')], default='fixed', verbose_name="Tipo de Abono")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"

class LoginAttempt(models.Model):
    username_attempted = models.CharField(max_length=150, verbose_name="Usuário Tentado")
    ip_address = models.GenericIPAddressField(verbose_name="Endereço IP")
    is_malicious = models.BooleanField(default=False, verbose_name="Tentativa Maliciosa")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Data e Hora")
    user = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Usuário Autenticado")

    def __str__(self):
        return f"Tentativa de Login por {self.username_attempted} em {self.timestamp}"

    class Meta:
        verbose_name = "Tentativa de Login"
        verbose_name_plural = "Tentativas de Login"

class UserActionLog(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, verbose_name="Usuário")
    action = models.CharField(max_length=255, verbose_name="Ação")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Data e Hora")
    ip_address = models.GenericIPAddressField(verbose_name="Endereço IP")

    def __str__(self):
        return f"{self.user.username} - {self.action} em {self.timestamp}"

    class Meta:
        verbose_name = "Log de Ação do Usuário"
        verbose_name_plural = "Logs de Ações do Usuário"

class Participacao(models.Model):
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, verbose_name="Funcionário")
    trimestre = models.CharField(max_length=10, verbose_name="Trimestre")
    dias_trabalhados = models.IntegerField(default=0, verbose_name="Dias Trabalhados")
    valor_bruto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Bruto")
    final_participacao = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Final")

    def __str__(self):
        return f"Participação de {self.funcionario.nome} - {self.trimestre}"

    class Meta:
        verbose_name = "Participação"
        verbose_name_plural = "Participações"

class AprovacaoSetor(models.Model):
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, verbose_name="Setor")
    trimestre = models.CharField(max_length=10, verbose_name="Trimestre")
    status = models.CharField(max_length=20, choices=[('pendente', 'Pendente'), ('aprovado', 'Aprovado'), ('pago', 'Pago')], default='pendente', verbose_name="Status")

    def __str__(self):
        return f"Aprovação de {self.setor.nome} - {self.trimestre}"

    class Meta:
        verbose_name = "Aprovação de Setor"
        verbose_name_plural = "Aprovações de Setores"

# Novo modelo Evento
class Evento(models.Model):
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, verbose_name="Funcionário")
    data = models.DateField(verbose_name="Data do Evento")
    tipo = models.CharField(max_length=50, verbose_name="Tipo de Evento")
    descricao = models.TextField(verbose_name="Descrição", blank=True)

    def __str__(self):
        return f"Evento de {self.funcionario.nome} - {self.data}"

    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"