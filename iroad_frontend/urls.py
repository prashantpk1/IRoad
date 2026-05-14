from django.urls import path

from iroad_frontend.views import (
    AboutPageView,
    ContactFormSubmitView,
    ContactPageView,
    HomePageView,
    MobileAboutUsView,
    PricingPageView,
    PrivacyPolicyView,
    TermsConditionsView,
)

app_name = 'iroad_frontend'

urlpatterns = [
    path('about/', AboutPageView.as_view(), name='about'),
    path('pricing/', PricingPageView.as_view(), name='pricing'),
    path('contact/', ContactPageView.as_view(), name='contact'),
    path(
        'contact/submit/',
        ContactFormSubmitView.as_view(),
        name='contact_submit',
    ),
    path(
        'privacy-policy/',
        PrivacyPolicyView.as_view(),
        name='privacy_policy',
    ),
    path(
        'terms-and-conditions/',
        TermsConditionsView.as_view(),
        name='terms_conditions',
    ),
    path(
        'mobile-about-us/',
        MobileAboutUsView.as_view(),
        name='mobile_about_us',
    ),
    path('', HomePageView.as_view(), name='home'),
]
