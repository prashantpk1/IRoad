"""Helpers for tenant ModelChoiceField dropdowns under django-tenants schema switching."""


def pin_model_choice_field(field, options):
    """
    Load ModelChoiceField options in memory so template render does not query
    after tenant context processors reset the DB connection to public schema.
    """
    empty_label = field.empty_label or '---------'
    label_from_instance = getattr(field, 'label_from_instance', None)
    pinned = [('', empty_label)]
    pks = []
    for obj in options:
        pks.append(obj.pk)
        label = label_from_instance(obj) if label_from_instance else str(obj)
        pinned.append((obj.pk, label))
    model = field.queryset.model
    field.queryset = model.objects.filter(pk__in=pks) if pks else model.objects.none()
    field.choices = pinned
