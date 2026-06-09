"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
    path('superadmin/', admin.site.urls),
    path('api/v1/mobile/', include(('mobile_api.urls', 'mobile_api'), namespace='mobile_api')),
    path('api/v1/', include('superadmin.api_urls')),
    path('tenant/', include(('iroad_tenants.urls', 'iroad_tenants'), namespace='iroad_tenants')),
    path('', include(('iroad_frontend.urls', 'iroad_frontend'), namespace='iroad_frontend')),
    path('', include('superadmin.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve STATIC_URL from STATICFILES_DIRS / finders (dev + django.test.Client).
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()

handler400 = 'iroad_frontend.error_views.bad_request'
handler403 = 'iroad_frontend.error_views.permission_denied'
handler404 = 'iroad_frontend.error_views.page_not_found'
handler500 = 'iroad_frontend.error_views.server_error'
