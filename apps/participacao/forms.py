# apps/participacao/forms.py
from django import forms
from .models import Setor

class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ['nome', 'recebe_participacao']



class PlanilhaParticipacaoForm(forms.Form):
    trimestre = forms.ChoiceField(label="Selecione o Trimestre", choices=[], required=True)
    file = forms.FileField(label="Selecione o Arquivo", help_text="Apenas arquivos .csv, .xlsx ou .xls", required=True)