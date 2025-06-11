from django.db import models

class RegraParticipacao(models.Model):
    indicador = models.CharField(max_length=50, unique=True, verbose_name="Indicador")
    periodo = models.CharField(
        max_length=10,
        choices=[('mensal', 'Mensal'), ('trimestral', 'Trimestral')],
        default='mensal',
        verbose_name="Período"
    )
    tolerancia = models.IntegerField(default=0, verbose_name="Tolerância")
    representatividade = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="Representatividade (%)")
    valor_subsequente = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="Valor Subsequente (%)")
    data_inicio = models.DateField(verbose_name="Data de Início")
    data_fim = models.DateField(null=True, blank=True, verbose_name="Data de Fim")

    def __str__(self):
        return f"{self.indicador} - {self.periodo}"

    class Meta:
        verbose_name = "Regra de Participação"
        verbose_name_plural = "Regras de Participação"

class ValoresParticipacao(models.Model):
    trimestre = models.CharField(max_length=10, unique=True, verbose_name="Trimestre")
    documentos_normais = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Documentos Normais")
    documentos_diferenciados = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Documentos Diferenciados")
    deducao_normal = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Dedução Normal")
    deducao_diferenciada = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Dedução Diferenciada")
    percentual_normal = models.DecimalField(max_digits=5, decimal_places=2, default=40.00, verbose_name="Percentual Normal (%)")
    percentual_diferenciada = models.DecimalField(max_digits=5, decimal_places=2, default=30.00, verbose_name="Percentual Diferenciado (%)")
    percentual_faturamento = models.DecimalField(max_digits=5, decimal_places=2, default=55.00, verbose_name="Percentual Faturamento (%)")
    percentual_demais = models.DecimalField(max_digits=5, decimal_places=2, default=45.00, verbose_name="Percentual Demais (%)")

    def __str__(self):
        return self.trimestre

    class Meta:
        verbose_name = "Valor de Participação"
        verbose_name_plural = "Valores de Participação"