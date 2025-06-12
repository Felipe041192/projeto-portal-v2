from django.template.defaultfilters import register
import locale

@register.filter(name='format_currency')
def format_currency(value):
    """Formata um valor como moeda (ex.: R$ 123.45)."""
    try:
        # Tentar configurar locale para pt_BR; usar fallback se falhar
        try:
            locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
        except locale.Error:
            locale.setlocale(locale.LC_ALL, '')  # Usa a localidade padrão do sistema
        return locale.currency(float(value), grouping=True)
    except (ValueError, TypeError, locale.Error):
        return "R$ 0,00"

@register.filter(name='lookup')
def lookup(dictionary, key):
    """Retorna o valor associado a uma chave em um dicionário."""
    return dictionary.get(key)

@register.filter(name='get_item')
def get_item(dictionary, key):
    """Retorna o valor associado a uma chave em um dicionário (alternativa a lookup)."""
    return dictionary.get(key)

@register.filter(name='zip')
def zip_lists(list1, list2):
    """Combina duas listas em pares."""
    return zip(list1, list2)