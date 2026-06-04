"""
Django 5.0 + Python 3.14 compatibility.

On Python 3.14+, ``copy(super())`` copies the super proxy instead of the
context instance, so ``{% include ... only %}`` fails with:
  AttributeError: 'super' object has no attribute 'dicts'

Django 5.2+ fixes BaseContext.__copy__; this patch applies the same fix for 5.0/5.1.
See https://code.djangoproject.com/ticket/35844
"""

from copy import copy as _copy


def _patch_basecontext_copy():
    try:
        import django
    except ImportError:
        return
    if django.VERSION >= (5, 2):
        return

    from django.template.context import BaseContext

    if getattr(BaseContext.__copy__, '_iroad_patched', False):
        return

    def __copy__(self):
        duplicate = BaseContext()
        duplicate.__class__ = self.__class__
        duplicate.__dict__ = _copy(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    __copy__._iroad_patched = True
    BaseContext.__copy__ = __copy__


_patch_basecontext_copy()
