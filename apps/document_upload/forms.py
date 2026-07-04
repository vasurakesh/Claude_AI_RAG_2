"""
apps/document_upload/forms.py
"""
from django import forms
from django.conf import settings
from apps.knowledge_base.models import KnowledgeBase
from apps.document_upload.models import Document


class DocumentUploadForm(forms.Form):
    knowledge_base = forms.ModelChoiceField(
        queryset=KnowledgeBase.objects.filter(is_active=True, is_deleted=False),
        label='Knowledge Base',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    # file input is handled raw in the template; files come via request.FILES.getlist('files')
    tags = forms.CharField(
        required=False,
        label='Tags',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. finance, Q3'}),
    )
    process_now = forms.BooleanField(
        required=False,
        initial=True,
        label='Process immediately',
        widget=forms.CheckboxInput(attrs={'class': 'custom-control-input'}),
    )


class DocumentSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Search…'}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses')] + list(Document.Status.choices),
        widget=forms.Select(attrs={'class': 'form-control form-control-sm'}),
    )
    kb = forms.ModelChoiceField(
        required=False,
        queryset=KnowledgeBase.objects.filter(is_active=True, is_deleted=False),
        empty_label='All knowledge bases',
        widget=forms.Select(attrs={'class': 'form-control form-control-sm'}),
    )
