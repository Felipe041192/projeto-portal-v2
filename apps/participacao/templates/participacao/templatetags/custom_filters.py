from django import template

register = template.Library()

# Exemplo: Adicione os filtros usados no projeto anterior
@register.filter
def custom_format(value):
    return f"R$ {float(value):.2f}"  # Exemplo de formatação de moeda