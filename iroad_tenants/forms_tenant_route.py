from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tenant_workspace.models import TenantLocationMaster, TenantRouteMaster


def _model_choice_pk_str(value):
    """Normalize ModelChoiceField / ModelChoiceIteratorValue to string PK for option attrs."""
    if value is None or value == '':
        return None
    inner = getattr(value, 'value', value)
    if inner is None:
        return None
    return str(inner)


class LocationPointSelect(forms.Select):
    """Route endpoint select with data-country-id on each option (for derived Has Customs UI)."""

    def __init__(self, *args, country_id_by_value=None, **kwargs):
        self.country_id_by_value = country_id_by_value or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        key = _model_choice_pk_str(value)
        if key:
            cid = self.country_id_by_value.get(key)
            if cid is not None:
                option.setdefault('attrs', {})
                option['attrs']['data-country-id'] = str(cid)
        return option


class TenantRouteMasterForm(forms.ModelForm):
    """PCS RT-001: derived route_label / has_customs; Phase 1 route_type choices; location gate."""

    _PHASE1_ROUTE_TYPES = (
        TenantRouteMaster.RouteType.DOMESTIC,
        TenantRouteMaster.RouteType.INTERNATIONAL,
    )

    def __init__(self, *args, **kwargs):
        allow_inactive_status = bool(kwargs.pop('allow_inactive_status', False))
        super().__init__(*args, **kwargs)
        # PCS gate for new route endpoints: Location must be Active + Serviceable.
        base_operational_qs = TenantLocationMaster.objects.filter(
            status=TenantLocationMaster.Status.ACTIVE,
            is_serviceable=True,
        )
        # Avoid QuerySet.union() here: it often drops select_related / breaks choice rendering for ModelChoiceField.
        if self.instance.pk:
            pk_set = set(
                base_operational_qs.values_list('pk', flat=True)
            )
            for loc_pk in (self.instance.origin_point_id, self.instance.destination_point_id):
                if loc_pk:
                    pk_set.add(loc_pk)
            location_qs = (
                TenantLocationMaster.objects.filter(pk__in=pk_set)
                .select_related('country')
                .order_by('display_label')
            )
        else:
            location_qs = base_operational_qs.select_related(
                'country'
            ).order_by('display_label')

        country_id_by_value = {}
        for loc in location_qs:
            country_id_by_value[str(loc.pk)] = str(loc.country_id)

        def _location_choice_label(obj):
            return f'{obj.location_code} — {obj.display_label}'

        self.fields['origin_point'].queryset = location_qs
        self.fields['destination_point'].queryset = location_qs
        self.fields['origin_point'].empty_label = _('Select origin location')
        self.fields['destination_point'].empty_label = _('Select destination location')
        self.fields['origin_point'].label_from_instance = _location_choice_label
        self.fields['destination_point'].label_from_instance = _location_choice_label
        self.fields['origin_point'].widget = LocationPointSelect(
            attrs={'class': 'form-select', 'id': 'originPoint'},
            country_id_by_value=country_id_by_value,
        )
        self.fields['origin_point'].widget.choices = self.fields['origin_point'].choices
        self.fields['destination_point'].widget = LocationPointSelect(
            attrs={'class': 'form-select', 'id': 'destinationPoint'},
            country_id_by_value=country_id_by_value,
        )
        self.fields['destination_point'].widget.choices = self.fields['destination_point'].choices

        if self.instance.pk and self.instance.route_type not in self._PHASE1_ROUTE_TYPES:
            self.fields['route_type'].choices = list(TenantRouteMaster.RouteType.choices)
        else:
            self.fields['route_type'].choices = [
                c for c in TenantRouteMaster.RouteType.choices if c[0] in self._PHASE1_ROUTE_TYPES
            ]

        if allow_inactive_status:
            self.fields['status'].choices = TenantRouteMaster.Status.choices
        else:
            self.fields['status'].choices = [
                (TenantRouteMaster.Status.ACTIVE, _('Active')),
            ]
        self.initial.setdefault('route_type', TenantRouteMaster.RouteType.DOMESTIC)
        self.initial.setdefault('status', TenantRouteMaster.Status.ACTIVE)
        self._allow_inactive_status = allow_inactive_status
        self.computed_has_customs = None
        if self.instance.pk and self.instance.origin_point_id and self.instance.destination_point_id:
            o = self.instance.origin_point
            d = self.instance.destination_point
            self.computed_has_customs = TenantRouteMaster.derive_has_customs(o, d)

    class Meta:
        model = TenantRouteMaster
        fields = (
            'route_type',
            'origin_point',
            'destination_point',
            'status',
            'distance_km',
            'estimated_duration_h',
            'has_toll_gates',
        )
        widgets = {
            'route_type': forms.Select(attrs={'class': 'form-select', 'id': 'routeType'}),
            'status': forms.Select(attrs={'class': 'form-select', 'id': 'status'}),
            'distance_km': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'id': 'distanceKm',
                    'placeholder': '0',
                    'min': '0',
                    'step': '0.1',
                }
            ),
            'estimated_duration_h': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'id': 'estimatedDurationH',
                    'placeholder': '0',
                    'min': '0',
                    'step': '0.5',
                }
            ),
            'has_toll_gates': forms.CheckboxInput(attrs={'id': 'hasTollGates'}),
        }

    def clean_distance_km(self):
        v = self.cleaned_data.get('distance_km')
        if v is not None and v < 0:
            raise ValidationError(_('Distance cannot be negative.'))
        return v

    def clean_estimated_duration_h(self):
        v = self.cleaned_data.get('estimated_duration_h')
        if v is not None and v < 0:
            raise ValidationError(_('Estimated duration cannot be negative.'))
        return v

    def clean(self):
        cleaned = super().clean()
        origin = cleaned.get('origin_point')
        dest = cleaned.get('destination_point')
        self.computed_has_customs = None
        if origin and dest:
            if origin.pk == dest.pk:
                self.add_error(
                    'destination_point',
                    _('Origin and destination must be different.'),
                )
            else:
                self.computed_has_customs = TenantRouteMaster.derive_has_customs(origin, dest)
        return cleaned

    def clean_status(self):
        status = self.cleaned_data.get('status')
        if not self._allow_inactive_status and status != TenantRouteMaster.Status.ACTIVE:
            raise ValidationError(_('Inactive is not allowed during create.'))
        return status

    def save(self, commit=True):
        instance = super().save(commit=False)
        origin = self.cleaned_data.get('origin_point')
        dest = self.cleaned_data.get('destination_point')
        if origin and dest:
            max_len = self._meta.model._meta.get_field('route_label').max_length
            instance.route_label = f'{origin.display_label} — {dest.display_label}'[:max_len]
            instance.has_customs = TenantRouteMaster.derive_has_customs(origin, dest)
        if commit:
            instance.save()
            self.save_m2m()
        return instance
