from django.contrib import messages
from django.contrib.sessions.models import Session
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, F, Q
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import DecimalField
from django.db.models.functions import Abs
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import TemplateView
from decimal import Decimal
import json

from .auth_helpers import (
    check_brute_force,
    create_auth_token,
    get_security_settings,
    log_access,
    record_failed_attempt,
    reset_failed_attempts,
)
from .forms import (
    AddOnsPricingPolicyForm,
    AdminUserForm,
    CountryForm,
    CurrencyForm,
    CommGatewayForm,
    BaseCurrencyForm,
    BankAccountForm,
    ExchangeRateForm,
    EventMappingForm,
    ForgotPasswordForm,
    LoginForm,
    GeneralTaxSettingsForm,
    GlobalSystemRulesForm,
    RoleForm,
    SetPasswordForm,
    LegalIdentityForm,
    NotificationTemplateForm,
    PlanPricingCycleForm,
    PaymentGatewayForm,
    PaymentMethodForm,
    PromoCodeForm,
    PushNotificationForm,
    SystemBannerForm,
    SubscriptionPlanForm,
    TaxCodeForm,
    InternalAlertRouteForm,
)
from .models import (
    AccessLog,
    AddOnsPricingPolicy,
    AdminAuthToken,
    AdminUser,
    BaseCurrencyConfig,
    BankAccount,
    Country,
    CommGateway,
    CommLog,
    Currency,
    EventMapping,
    GeneralTaxSettings,
    GlobalSystemRules,
    LegalIdentity,
    NotificationTemplate,
    PaymentGateway,
    PaymentMethod,
    PlanPricingCycle,
    PromoCode,
    PushNotification,
    Role,
    SubscriptionPlan,
    SystemBanner,
    TaxCode,
    ExchangeRate,
    FXRateChangeLog,
)


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class LoginView(View):
    template_name = 'auth/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, self.template_name, {'form': LoginForm()})

    def post(self, request):
        form = LoginForm(request.POST)
        email = request.POST.get('email', '').lower().strip()
        ip = _client_ip(request)

        # STEP 1: Check brute force FIRST
        brute = check_brute_force(email)
        if brute['is_locked']:
            log_access('Login', 'Blocked', email, ip)
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'error': (
                        f'Account locked. Try again in '
                        f"{brute['remaining_minutes']} minute(s)."
                    ),
                    'is_locked': True,
                },
            )

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'error': 'Please enter valid email and password.',
                },
            )

        # STEP 2: Check user exists
        try:
            user = AdminUser.objects.get(
                email=form.cleaned_data['email'].lower().strip()
            )
        except AdminUser.DoesNotExist:
            record_failed_attempt(email)
            log_access('Login', 'Failed', email, ip)
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'error': 'Invalid email or password.',
                    'failed_count': check_brute_force(email)['failed_count'],
                },
            )

        # STEP 3: Check status
        if user.status == 'Suspended':
            log_access('Login', 'Failed', email, ip)
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'error': (
                        'Your account has been suspended. '
                        'Contact your administrator.'
                    ),
                },
            )

        if user.status == 'Pending_Activation':
            log_access('Login', 'Failed', email, ip)
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'error': (
                        'Your account is not yet activated. '
                        'Please use the invite link sent to you.'
                    ),
                },
            )

        # STEP 4: Check password
        if not user.check_password(form.cleaned_data['password']):
            record_failed_attempt(email)
            log_access('Login', 'Failed', email, ip)

            # Re-check AFTER recording — may have just hit the limit
            brute_after = check_brute_force(email)
            if brute_after['is_locked']:
                return render(
                    request,
                    'auth/login.html',
                    {
                        'form': form,
                        'error': (
                            'Account locked due to too many failed '
                            'attempts. Try again in '
                            f"{brute_after['remaining_minutes']} "
                            'minute(s).'
                        ),
                        'is_locked': True,
                    },
                )

            settings_obj = get_security_settings()
            remaining_attempts = (
                settings_obj.max_failed_logins - brute_after['failed_count']
            )
            return render(
                request,
                'auth/login.html',
                {
                    'form': form,
                    'error': (
                        'Invalid email or password. '
                        f'{remaining_attempts} attempt(s) remaining.'
                    ),
                },
            )

        # STEP 5: All good — login
        reset_failed_attempts(email)
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])

        login(request, user)
        request.session['last_activity'] = timezone.now().isoformat()

        log_access('Login', 'Success', email, ip)
        return redirect('dashboard')


class LogoutView(View):
    def get(self, request):
        if request.user.is_authenticated:
            log_access('Logout', 'Success', request.user.email, _client_ip(request))
        logout(request)
        return redirect(reverse('login'))

    def post(self, request):
        if request.user.is_authenticated:
            log_access('Logout', 'Success', request.user.email, _client_ip(request))
        logout(request)
        return redirect(reverse('login'))


class ForgotPasswordView(View):
    """Request password reset (email always gets same response text)."""

    template_request = 'auth/reset_password.html'
    template_sent = 'auth/reset_password_sent.html'
    success_message = (
        'If this email exists in our system, '
        'a reset link has been generated.'
    )

    def get(self, request):
        return render(
            request,
            self.template_request,
            {'form': ForgotPasswordForm()},
        )

    def post(self, request):
        form = ForgotPasswordForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_request,
                {'form': form},
            )

        email = form.cleaned_data['email'].lower().strip()
        reset_url = None

        try:
            user = AdminUser.objects.get(email=email)
        except AdminUser.DoesNotExist:
            user = None
        else:
            if user.status in ('Active', 'Pending_Activation'):
                token = create_auth_token(user, 'password_reset')
                reset_url = request.build_absolute_uri(
                    f'/new-password/{token.token}/'
                )
                # TODO Phase 7: Send reset_url via email here

        return render(
            request,
            self.template_sent,
            {
                'success_message': self.success_message,
                'reset_url': reset_url,
            },
        )


class ResetPasswordConfirmView(View):
    """Public: choose new password using password_reset token."""

    template_form = 'auth/new_password.html'
    template_error = 'auth/token_error.html'

    def _render_error(self, request, message):
        return render(
            request,
            self.template_error,
            {'error_message': message},
        )

    def _get_reset_token(self, raw_token):
        try:
            return AdminAuthToken.objects.select_related('admin_user').get(
                token=raw_token,
                token_type=AdminAuthToken.TokenType.PASSWORD_RESET,
            )
        except AdminAuthToken.DoesNotExist:
            return None

    def get(self, request, token):
        reset_tok = self._get_reset_token(token)
        if reset_tok is None:
            return self._render_error(request, 'Invalid reset link.')
        if reset_tok.is_used:
            return self._render_error(
                request,
                'This reset link has already been used.',
            )
        if reset_tok.is_expired:
            return self._render_error(
                request,
                'This reset link has expired.',
            )
        return render(
            request,
            self.template_form,
            {
                'form': SetPasswordForm(),
                'account_email': reset_tok.admin_user.email,
            },
        )

    def post(self, request, token):
        reset_tok = self._get_reset_token(token)
        if reset_tok is None:
            return self._render_error(request, 'Invalid reset link.')
        if reset_tok.is_used:
            return self._render_error(
                request,
                'This reset link has already been used.',
            )
        if reset_tok.is_expired:
            return self._render_error(
                request,
                'This reset link has expired.',
            )

        form = SetPasswordForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_form,
                {
                    'form': form,
                    'account_email': reset_tok.admin_user.email,
                },
            )

        user = reset_tok.admin_user
        user.set_password(form.cleaned_data['password'])
        user.save(update_fields=['password'])

        reset_tok.is_used = True
        reset_tok.save(update_fields=['is_used'])

        reset_failed_attempts(user.email)

        messages.success(
            request,
            'Password reset successful. Please login.',
        )
        return redirect(reverse('login'))


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('page_title', 'Dashboard')
        return context


class AccessLogListView(LoginRequiredMixin, View):
    template_name = 'security/access_log.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('dashboard'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        qs = AccessLog.objects.all()

        status_filter = request.GET.get('status', 'All')
        if status_filter in [
            AccessLog.Status.SUCCESS,
            AccessLog.Status.FAILED,
            AccessLog.Status.BLOCKED,
        ]:
            qs = qs.filter(status=status_filter)

        attempt_filter = request.GET.get('attempt_type', 'All')
        if attempt_filter in [
            AccessLog.AttemptType.LOGIN,
            AccessLog.AttemptType.LOGOUT,
        ]:
            qs = qs.filter(attempt_type=attempt_filter)

        search_email = request.GET.get('q', '').strip()
        if search_email:
            qs = qs.filter(email_used__icontains=search_email)

        from_date = request.GET.get('from_date', '').strip()
        to_date = request.GET.get('to_date', '').strip()
        fd = parse_date(from_date) if from_date else None
        td = parse_date(to_date) if to_date else None
        if fd:
            qs = qs.filter(timestamp__date__gte=fd)
        if td:
            qs = qs.filter(timestamp__date__lte=td)

        qs = qs.order_by('-timestamp')
        total_count = qs.count()

        paginator = Paginator(qs, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page', None)

        context = {
            'access_logs': page_obj,
            'total_count': total_count,
            'page_title': 'Authentication Access Log',
            'status_filter': status_filter,
            'attempt_type_filter': attempt_filter,
            'search_email': search_email,
            'from_date': from_date,
            'to_date': to_date,
            'filter_query': query_params.urlencode(),
        }
        return render(request, self.template_name, context)


class RoleListView(LoginRequiredMixin, View):
    template_name = 'system_users/roles/role_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        roles_qs = Role.objects.all().order_by('role_name_en')
        if search_query:
            roles_qs = roles_qs.filter(role_name_en__icontains=search_query)
        if status_filter in ['Active', 'Inactive']:
            roles_qs = roles_qs.filter(status=status_filter)

        total_count = roles_qs.count()
        paginator = Paginator(roles_qs, 10)
        page_number = request.GET.get('page', 1)
        roles_page = paginator.get_page(page_number)

        context = {
            'roles': roles_page,
            'search_query': search_query,
            'status_filter': status_filter,
            'total_count': total_count,
        }
        return render(request, self.template_name, context)


class RoleCreateView(LoginRequiredMixin, View):
    template_name = 'system_users/roles/role_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('role_list'))
        return None

    def get(self, request):
        root_redirect = self._require_root(request)
        if root_redirect:
            return root_redirect
        return render(request, self.template_name, {'form': RoleForm()})

    def post(self, request):
        root_redirect = self._require_root(request)
        if root_redirect:
            return root_redirect

        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save(commit=False)
            role.created_by = request.user
            role.save()
            messages.success(request, 'Role created successfully.')
            return redirect(reverse('role_list'))

        return render(request, self.template_name, {'form': form})


class RoleUpdateView(LoginRequiredMixin, View):
    template_name = 'system_users/roles/role_form.html'

    def _require_root_or_redirect(self, request, redirect_to):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(redirect_to)
        return None

    def get(self, request, pk):
        redirect_resp = self._require_root_or_redirect(request, reverse('role_list'))
        if redirect_resp:
            return redirect_resp

        role = get_object_or_404(Role, pk=pk)
        if role.is_system_default:
            messages.error(request, 'System default roles cannot be modified')
            return redirect(reverse('role_list'))

        return render(request, self.template_name, {'form': RoleForm(instance=role)})

    def post(self, request, pk):
        redirect_resp = self._require_root_or_redirect(request, reverse('role_list'))
        if redirect_resp:
            return redirect_resp

        role = get_object_or_404(Role, pk=pk)
        if role.is_system_default:
            messages.error(request, 'System default roles cannot be modified')
            return redirect(reverse('role_list'))

        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            role = form.save(commit=False)
            role.updated_by = request.user
            role.save()
            messages.success(request, 'Role updated successfully.')
            return redirect(reverse('role_list'))

        return render(request, self.template_name, {'form': form})


class RoleToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('role_list'))

        role = get_object_or_404(Role, pk=pk)
        if role.is_system_default:
            messages.error(request, 'System default roles cannot be modified')
            return redirect(reverse('role_list'))

        if role.status == 'Active':
            target_status = 'Inactive'
            active_users = AdminUser.objects.filter(role=role, status='Active')
            if active_users.exists():
                messages.error(
                    request,
                    f'Cannot deactivate role — {active_users.count()} users are currently assigned to it',
                )
                return redirect(reverse('role_list'))
        else:
            target_status = 'Active'

        role.status = target_status
        role.updated_by = request.user
        role.save(update_fields=['status', 'updated_by'])

        messages.success(request, 'Role status updated successfully.')
        return redirect(reverse('role_list'))


class RoleDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('role_list'))

        # Hard delete is forbidden; always redirect with error.
        messages.error(request, 'Roles cannot be deleted. Set to Inactive instead.')
        return redirect(reverse('role_list'))


def _revoke_user_sessions(user):
    """
    Phase 1 session invalidation for suspended users.
    This deletes DB-backed sessions that contain the suspended user id.
    """
    user_id = str(user.pk)
    for session in Session.objects.all():
        try:
            decoded = session.get_decoded()
        except Exception:
            continue
        auth_user_id = decoded.get('_auth_user_id')
        if auth_user_id is not None and str(auth_user_id) == user_id:
            session.delete()


class AdminUserListView(LoginRequiredMixin, View):
    template_name = 'system_users/admin_users/admin_user_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')
        role_filter = request.GET.get('role', 'All')

        users_qs = AdminUser.objects.all().select_related('role', 'created_by', 'updated_by')

        if search_query:
            users_qs = users_qs.filter(
                Q(first_name__icontains=search_query)
                | Q(last_name__icontains=search_query)
                | Q(email__icontains=search_query)
            )

        if status_filter in [choice[0] for choice in AdminUser.STATUS_CHOICES]:
            users_qs = users_qs.filter(status=status_filter)

        if role_filter != 'All' and role_filter:
            users_qs = users_qs.filter(role_id=role_filter)

        users_qs = users_qs.order_by('first_name', 'last_name')
        total_count = users_qs.count()

        paginator = Paginator(users_qs, 10)
        page_number = request.GET.get('page', 1)
        users_page = paginator.get_page(page_number)

        context = {
            'admin_users': users_page,
            'search_query': search_query,
            'status_filter': status_filter,
            'role_filter': role_filter,
            'total_count': total_count,
            'roles': Role.objects.all().order_by('role_name_en'),
            'statuses': AdminUser.STATUS_CHOICES,
            'page_title': 'Admin Users Master',
        }
        return render(request, self.template_name, context)


class AdminUserCreateView(LoginRequiredMixin, View):
    template_name = 'system_users/admin_users/admin_user_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('admin_user_list'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        form = AdminUserForm(initial={'status': 'Pending_Activation'})
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        form = AdminUserForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        user = form.save(commit=False)
        # Phase 1 rule: invite flow (no password/email yet)
        user.status = 'Pending_Activation'
        user.created_by = request.user
        user.updated_by = request.user

        # TODO Phase 2: Send invite email here

        user.save()

        auth_token = create_auth_token(user, 'invite')
        invite_url = request.build_absolute_uri(
            f'/set-password/{auth_token.token}/'
        )
        # TODO Phase 7: Send invite_url via email here

        return render(
            request,
            'system_users/admin_users/invite_success.html',
            {'invite_url': invite_url},
        )


class SetPasswordView(View):
    """Public: activate invited admin via token."""

    template_form = 'auth/set_password.html'
    template_error = 'auth/token_error.html'

    def _render_error(self, request, message):
        return render(
            request,
            self.template_error,
            {'error_message': message},
        )

    def _get_invite_token(self, raw_token):
        try:
            return AdminAuthToken.objects.select_related('admin_user').get(
                token=raw_token,
                token_type=AdminAuthToken.TokenType.INVITE,
            )
        except AdminAuthToken.DoesNotExist:
            return None

    def get(self, request, token):
        invite = self._get_invite_token(token)
        if invite is None:
            return self._render_error(request, 'Invalid invite link.')
        if invite.is_used:
            return self._render_error(
                request,
                'This invite link has already been used.',
            )
        if invite.is_expired:
            return self._render_error(
                request,
                'This invite link has expired.',
            )
        return render(
            request,
            self.template_form,
            {
                'form': SetPasswordForm(),
                'invite_email': invite.admin_user.email,
            },
        )

    def post(self, request, token):
        invite = self._get_invite_token(token)
        if invite is None:
            return self._render_error(request, 'Invalid invite link.')
        if invite.is_used:
            return self._render_error(
                request,
                'This invite link has already been used.',
            )
        if invite.is_expired:
            return self._render_error(
                request,
                'This invite link has expired.',
            )

        form = SetPasswordForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_form,
                {
                    'form': form,
                    'invite_email': invite.admin_user.email,
                },
            )

        user = invite.admin_user
        password = form.cleaned_data['password']
        user.set_password(password)
        user.status = 'Active'
        user.save(update_fields=['password', 'status'])

        invite.is_used = True
        invite.save(update_fields=['is_used'])

        ip = _client_ip(request)
        log_access('Login', 'Success', user.email, ip)

        messages.success(
            request,
            'Password set successfully. Please login.',
        )
        return redirect(reverse('login'))


class AdminUserUpdateView(LoginRequiredMixin, View):
    template_name = 'system_users/admin_users/admin_user_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('admin_user_list'))
        return None

    def get(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        target_user = get_object_or_404(AdminUser, pk=pk)
        form = AdminUserForm(instance=target_user)
        return render(request, self.template_name, {'form': form})

    def post(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        target_user = get_object_or_404(AdminUser, pk=pk)
        original_role = target_user.role

        form = AdminUserForm(request.POST, instance=target_user)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        # Block root admin role changes.
        new_role = form.cleaned_data.get('role')
        # NOTE: ModelForm mutates the instance during validation, so we must
        # compare against the original role captured before form.is_valid().
        if target_user.is_root and new_role != original_role:
            messages.error(request, 'Root admin role can NEVER be changed')
            return redirect(reverse('admin_user_edit', args=[pk]))

        # Extra safety: root admin cannot be suspended.
        if target_user.is_root and form.cleaned_data.get('status') == 'Suspended':
            messages.error(request, 'Root admin cannot be suspended')
            return redirect(reverse('admin_user_edit', args=[pk]))

        user = form.save(commit=False)
        user.updated_by = request.user
        user.save()
        messages.success(request, 'Admin user updated successfully.')
        return redirect(reverse('admin_user_list'))


class AdminUserDetailView(LoginRequiredMixin, View):
    template_name = 'system_users/admin_users/admin_user_detail.html'

    def get(self, request, pk):
        target_user = get_object_or_404(AdminUser, pk=pk)
        return render(request, self.template_name, {'target_user': target_user, 'page_title': 'Admin User Details'})


class AdminUserToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('admin_user_list'))

        target_user = get_object_or_404(AdminUser, pk=pk)

        if target_user.is_root:
            messages.error(request, 'Root admin cannot be suspended')
            return redirect(reverse('admin_user_list'))

        # If target is currently active/pending => suspend, else => activate.
        is_suspending = target_user.status != 'Suspended'
        if is_suspending and target_user.pk == request.user.pk:
            messages.error(request, 'You cannot suspend your own account')
            return redirect(reverse('admin_user_list'))

        if is_suspending:
            # Phase 1: suspend + invalidate active sessions
            target_user.status = 'Suspended'
            target_user.updated_by = request.user
            target_user.save(update_fields=['status', 'updated_by'])

            # TODO Phase 2: Revoke JWT token from Redis here
            _revoke_user_sessions(target_user)
            messages.success(request, 'Admin user suspended successfully.')
        else:
            target_user.status = 'Active'
            target_user.updated_by = request.user
            target_user.save(update_fields=['status', 'updated_by'])
            messages.success(request, 'Admin user activated successfully.')

        return redirect(reverse('admin_user_list'))


class SystemUsersAnalyticsView(LoginRequiredMixin, View):
    template_name = 'system_users/analytics/users_analytics.html'

    def get(self, request):
        from datetime import timedelta

        total_staff = AdminUser.objects.exclude(status='Suspended').count()
        suspended_count = AdminUser.objects.filter(status='Suspended').count()
        pending_count = AdminUser.objects.filter(status='Pending_Activation').count()

        total_active = AdminUser.objects.filter(status='Active').count()
        two_fa_enabled_count = AdminUser.objects.filter(
            two_factor_enabled=True,
            status='Active',
        ).count()
        two_fa_rate = (two_fa_enabled_count / total_active * 100) if total_active > 0 else 0

        stale_threshold = timezone.now() - timedelta(days=30)
        stale_accounts_qs = (
            AdminUser.objects.filter(last_login_at__lt=stale_threshold, status='Active')
            .select_related('role')
            .order_by('-last_login_at')
        )

        stale_accounts = []
        now = timezone.now()
        for u in stale_accounts_qs:
            days_since = (now.date() - u.last_login_at.date()).days if u.last_login_at else None
            stale_accounts.append(
                {
                    'name': f'{u.first_name} {u.last_name}',
                    'email': u.email,
                    'role': u.role.role_name_en if u.role else None,
                    'last_login_at': u.last_login_at,
                    'days_since_login': days_since,
                }
            )

        # Role distribution: Active users per role (include Unassigned if role is null)
        role_distribution = []
        active_users_by_role = (
            AdminUser.objects.filter(status='Active')
            .values('role')
            .annotate(count=Count('id'))
        )

        counts_by_role_id = {row['role']: row['count'] for row in active_users_by_role}
        for role in Role.objects.all().order_by('role_name_en'):
            role_distribution.append(
                {
                    'role_name': role.role_name_en,
                    'count': counts_by_role_id.get(role.pk, 0),
                }
            )
        if None in counts_by_role_id:
            role_distribution.append({'role_name': 'Unassigned', 'count': counts_by_role_id.get(None, 0)})

        recently_created = list(
            AdminUser.objects.select_related('role').order_by('-created_at')[:5]
        )

        context = {
            'total_staff': total_staff,
            'suspended_count': suspended_count,
            'pending_count': pending_count,
            'two_fa_enabled_count': two_fa_enabled_count,
            'two_fa_rate': round(two_fa_rate, 2),
            'stale_accounts': stale_accounts,
            'role_distribution': role_distribution,
            'recently_created': recently_created,
            'page_title': 'System Users Analytics',
        }
        return render(request, self.template_name, context)


class CountryListView(LoginRequiredMixin, View):
    template_name = 'master_data/countries/country_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        countries_qs = Country.objects.all()

        if search_query:
            countries_qs = countries_qs.filter(
                Q(name_en__icontains=search_query)
                | Q(country_code__icontains=search_query)
            )

        if status_filter == 'Active':
            countries_qs = countries_qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            countries_qs = countries_qs.filter(is_active=False)

        countries_qs = countries_qs.order_by('name_en')
        total_count = countries_qs.count()

        paginator = Paginator(countries_qs, 15)
        page_number = request.GET.get('page', 1)
        countries_page = paginator.get_page(page_number)

        context = {
            'countries': countries_page,
            'search_query': search_query,
            'status_filter': status_filter,
            'total_count': total_count,
            'page_title': 'Countries Master',
        }
        return render(request, self.template_name, context)


class CountryCreateView(LoginRequiredMixin, View):
    template_name = 'master_data/countries/country_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('country_list'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        form = CountryForm(is_edit=False)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': False,
            },
        )

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        form = CountryForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': False,
                },
            )

        country = form.save(commit=False)
        country.country_code = country.country_code.upper().strip()
        country.created_by = request.user
        country.save()

        messages.success(request, 'Country created successfully.')
        # TODO Phase 10: Invalidate country cache here
        return redirect(reverse('country_list'))


class CountryUpdateView(LoginRequiredMixin, View):
    template_name = 'master_data/countries/country_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('country_list'))
        return None

    def get(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        country = get_object_or_404(Country, pk=pk)
        form = CountryForm(instance=country, is_edit=True)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': True,
                'country': country,
            },
        )

    def post(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        country = get_object_or_404(Country, pk=pk)
        form = CountryForm(request.POST, instance=country, is_edit=True)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': True,
                    'country': country,
                },
            )

        form.save()
        messages.success(request, 'Country updated successfully.')
        # TODO Phase 10: Invalidate country cache here
        return redirect(reverse('country_list'))


class CountryToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('country_list'))

        country = get_object_or_404(Country, pk=pk)

        if country.is_active:
            # TODO Phase 5: Check if country is linked to active Tenants
            #               before deactivating — implement when Tenant
            #               model exists
            country.is_active = False
            messages.success(request, 'Country deactivated successfully.')
        else:
            country.is_active = True
            messages.success(request, 'Country activated successfully.')

        country.save(update_fields=['is_active'])
        # TODO Phase 10: Invalidate country cache here
        return redirect(reverse('country_list'))


class CountryDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Countries cannot be deleted. Deactivate instead.')
        return redirect(reverse('country_list'))

    def get(self, request, pk):
        messages.error(request, 'Countries cannot be deleted. Deactivate instead.')
        return redirect(reverse('country_list'))


class CurrencyListView(LoginRequiredMixin, View):
    template_name = 'master_data/currencies/currency_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        currencies_qs = Currency.objects.all()

        if search_query:
            currencies_qs = currencies_qs.filter(
                Q(name_en__icontains=search_query)
                | Q(currency_code__icontains=search_query)
            )

        if status_filter == 'Active':
            currencies_qs = currencies_qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            currencies_qs = currencies_qs.filter(is_active=False)

        currencies_qs = currencies_qs.order_by('name_en')
        total_count = currencies_qs.count()

        paginator = Paginator(currencies_qs, 15)
        page_number = request.GET.get('page', 1)
        currencies_page = paginator.get_page(page_number)

        context = {
            'currencies': currencies_page,
            'search_query': search_query,
            'status_filter': status_filter,
            'total_count': total_count,
            'page_title': 'Currencies Master',
        }
        return render(request, self.template_name, context)


class CurrencyCreateView(LoginRequiredMixin, View):
    template_name = 'master_data/currencies/currency_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('currency_list'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        form = CurrencyForm(is_edit=False)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': False,
            },
        )

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        form = CurrencyForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': False,
                },
            )

        currency = form.save(commit=False)
        currency.currency_code = currency.currency_code.upper().strip()
        currency.created_by = request.user
        currency.save()

        messages.success(request, 'Currency created successfully.')
        return redirect(reverse('currency_list'))


class CurrencyUpdateView(LoginRequiredMixin, View):
    template_name = 'master_data/currencies/currency_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('currency_list'))
        return None

    def get(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        currency = get_object_or_404(Currency, pk=pk)
        form = CurrencyForm(instance=currency, is_edit=True)
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': True,
                'currency': currency,
            },
        )

    def post(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        currency = get_object_or_404(Currency, pk=pk)
        form = CurrencyForm(request.POST, instance=currency, is_edit=True)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': True,
                    'currency': currency,
                },
            )

        # CRITICAL: Enforce immutable PK even if a client bypasses disabled field.
        form.instance.currency_code = currency.currency_code
        form.save()

        messages.success(request, 'Currency updated successfully.')
        return redirect(reverse('currency_list'))


class CurrencyToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('currency_list'))

        currency = get_object_or_404(Currency, pk=pk)

        if currency.is_active:
            # TODO Phase 6: Check if currency is linked to active
            #               Subscription Plans or Payment Methods
            #               before deactivating
            currency.is_active = False
            messages.success(request, 'Currency deactivated successfully.')
        else:
            currency.is_active = True
            messages.success(request, 'Currency activated successfully.')

        currency.save(update_fields=['is_active'])
        return redirect(reverse('currency_list'))


class CurrencyDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Currencies cannot be deleted. Deactivate instead.')
        return redirect(reverse('currency_list'))

    def get(self, request, pk):
        messages.error(request, 'Currencies cannot be deleted. Deactivate instead.')
        return redirect(reverse('currency_list'))


class GeneralTaxSettingsView(LoginRequiredMixin, View):
    template_name = 'system_config/general_tax_settings.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('dashboard'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = GeneralTaxSettings.objects.get_or_create(
            setting_id='GLOBAL-TAX-SETTING',
            defaults={
                'prices_include_tax': False,
                'location_verification': 'Profile_Only',
            },
        )
        form = GeneralTaxSettingsForm(instance=obj)
        return render(request, self.template_name, {'form': form, 'obj': obj})

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = GeneralTaxSettings.objects.get_or_create(
            setting_id='GLOBAL-TAX-SETTING',
            defaults={
                'prices_include_tax': False,
                'location_verification': 'Profile_Only',
            },
        )
        form = GeneralTaxSettingsForm(request.POST, instance=obj)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'obj': obj},
            )

        form.instance.updated_by = request.user
        form.instance.save(update_fields=['prices_include_tax', 'location_verification', 'updated_by', 'updated_at'])
        messages.success(request, 'General tax settings saved successfully.')
        return redirect(reverse('general_tax_settings'))


class LegalIdentityView(LoginRequiredMixin, View):
    template_name = 'system_config/legal_identity.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('dashboard'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = LegalIdentity.objects.get_or_create(
            identity_id='GLOBAL-LEGAL-IDENTITY',
            defaults={
                'company_logo': None,
                'company_name_en': 'IRoad',
                'company_name_ar': 'IRoad',
                'company_country_code': None,
                'commercial_register': 'N/A',
                'tax_number': 'N/A',
                'registered_address': 'N/A',
                'support_email': 'admin@example.com',
                'support_phone': '',
            },
        )
        form = LegalIdentityForm(instance=obj)
        return render(request, self.template_name, {'form': form, 'obj': obj})

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = LegalIdentity.objects.get_or_create(
            identity_id='GLOBAL-LEGAL-IDENTITY',
            defaults={
                'company_logo': None,
                'company_name_en': 'IRoad',
                'company_name_ar': 'IRoad',
                'company_country_code': None,
                'commercial_register': 'N/A',
                'tax_number': 'N/A',
                'registered_address': 'N/A',
                'support_email': 'admin@example.com',
                'support_phone': '',
            },
        )

        form = LegalIdentityForm(request.POST, request.FILES, instance=obj)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'obj': obj},
            )

        form.instance.updated_by = request.user
        form.instance.save(update_fields=[
            'company_logo',
            'company_name_en',
            'company_name_ar',
            'company_country_code',
            'commercial_register',
            'tax_number',
            'registered_address',
            'support_email',
            'support_phone',
            'updated_by',
            'updated_at',
        ])
        messages.success(request, 'IRoad legal identity saved successfully.')
        return redirect(reverse('legal_identity'))


class GlobalSystemRulesView(LoginRequiredMixin, View):
    template_name = 'system_config/global_system_rules.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('dashboard'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = GlobalSystemRules.objects.get_or_create(
            rule_id='GLOBAL-SYSTEM-RULES',
            defaults={
                'system_timezone': 'Asia/Riyadh',
                'default_date_format': 'DD/MM/YYYY',
                'grace_period_days': 3,
                'standard_billing_cycle': 30,
            },
        )
        form = GlobalSystemRulesForm(instance=obj)
        return render(request, self.template_name, {'form': form, 'obj': obj})

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        obj, _created = GlobalSystemRules.objects.get_or_create(
            rule_id='GLOBAL-SYSTEM-RULES',
            defaults={
                'system_timezone': 'Asia/Riyadh',
                'default_date_format': 'DD/MM/YYYY',
                'grace_period_days': 3,
                'standard_billing_cycle': 30,
            },
        )

        form = GlobalSystemRulesForm(request.POST, instance=obj)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'obj': obj},
            )

        form.instance.updated_by = request.user
        form.instance.save(update_fields=[
            'system_timezone',
            'default_date_format',
            'grace_period_days',
            'standard_billing_cycle',
            'updated_by',
            'updated_at',
        ])
        messages.success(request, 'Global system rules saved successfully.')
        return redirect(reverse('global_system_rules'))


class BaseCurrencyView(LoginRequiredMixin, View):
    template_name = 'system_config/base_currency.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('dashboard'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        # Phase 4: create once; Phase 5 will enforce immutability based on transactions.
        sar = Currency.objects.filter(currency_code='SAR').first()
        obj, _created = BaseCurrencyConfig.objects.get_or_create(
            setting_id='GLOBAL-BASE-CURRENCY',
            defaults={'base_currency': sar},
        )
        form = BaseCurrencyForm(instance=obj)
        return render(request, self.template_name, {'form': form, 'obj': obj})

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp

        sar = Currency.objects.filter(currency_code='SAR').first()
        obj, _created = BaseCurrencyConfig.objects.get_or_create(
            setting_id='GLOBAL-BASE-CURRENCY',
            defaults={'base_currency': sar},
        )

        form = BaseCurrencyForm(request.POST, instance=obj)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'obj': obj},
            )

        # TODO Phase 5: Check if any financial transactions
        #               exist before allowing change.
        #               If yes, block change entirely.
        form.instance.updated_by = request.user
        form.instance.save(update_fields=['base_currency', 'updated_by', 'updated_at'])
        messages.success(request, 'Base currency saved successfully.')
        return redirect(reverse('base_currency'))


def _get_base_currency_code():
    """
    Helper to fetch the current base currency code (used to exclude it from FX rates).
    """
    obj, _created = BaseCurrencyConfig.objects.get_or_create(
        setting_id='GLOBAL-BASE-CURRENCY',
        defaults={
            'base_currency': Currency.objects.filter(currency_code='SAR').first(),
        },
    )
    if obj.base_currency_id:
        return obj.base_currency.currency_code
    return None


def _require_root_or_redirect(request):
    if not getattr(request.user, 'is_root', False):
        messages.error(request, 'Access denied: root admin only.')
        return redirect(reverse('dashboard'))
    return None


class ExchangeRateListView(LoginRequiredMixin, View):
    template_name = 'system_config/exchange_rates/fx_list.html'

    def get(self, request):
        status_filter = request.GET.get('status', 'All')

        base_code = _get_base_currency_code()
        base_config = BaseCurrencyConfig.objects.get_or_create(
            setting_id='GLOBAL-BASE-CURRENCY',
            defaults={'base_currency': Currency.objects.filter(currency_code='SAR').first()},
        )[0]
        base_currency = base_config.base_currency

        qs = (
            ExchangeRate.objects.select_related('currency')
            .order_by('-updated_at')
        )

        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        total_count = qs.count()
        paginator = Paginator(qs, 15)
        page_number = request.GET.get('page', 1)
        rates_page = paginator.get_page(page_number)

        context = {
            'exchange_rates': rates_page,
            'status_filter': status_filter,
            'total_count': total_count,
            'base_currency': base_currency,
            'base_currency_code': base_code,
        }
        return render(request, self.template_name, context)


class ExchangeRateCreateView(LoginRequiredMixin, View):
    template_name = 'system_config/exchange_rates/fx_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        base_code = _get_base_currency_code()
        form = ExchangeRateForm(base_currency_code=base_code)
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': False, 'base_currency_code': base_code},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        base_code = _get_base_currency_code()
        form = ExchangeRateForm(request.POST, base_currency_code=base_code)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False, 'base_currency_code': base_code},
            )

        currency = form.cleaned_data.get('currency')
        if currency and base_code and currency.currency_code == base_code:
            form.add_error('currency', 'Currency must not be the base currency.')
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False, 'base_currency_code': base_code},
            )

        if currency and ExchangeRate.objects.filter(currency=currency, is_active=True).exists():
            form.add_error(
                'currency',
                'An active rate already exists for this currency. Edit it instead.',
            )
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False, 'base_currency_code': base_code},
            )

        rate = form.save(commit=False)
        rate.updated_by = request.user
        rate.save()

        FXRateChangeLog.objects.create(
            currency=rate.currency,
            old_rate=Decimal('0.000000'),
            new_rate=rate.exchange_rate,
            notes='Initial rate set',
            changed_by=request.user,
        )

        messages.success(request, 'Exchange rate created successfully.')
        return redirect(reverse('fx_rate_list'))


class ExchangeRateUpdateView(LoginRequiredMixin, View):
    template_name = 'system_config/exchange_rates/fx_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        base_code = _get_base_currency_code()
        rate = get_object_or_404(ExchangeRate, pk=pk)
        form = ExchangeRateForm(instance=rate, base_currency_code=base_code)
        form.fields['currency'].disabled = True

        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': True,
                'base_currency_code': base_code,
                'rate_obj': rate,
            },
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        rate = get_object_or_404(ExchangeRate, pk=pk)

        # Optional action: toggle active status without touching the FX value.
        if request.POST.get('action') == 'toggle_status':
            new_active = not rate.is_active
            rate.is_active = new_active
            rate.updated_by = request.user
            rate.save(update_fields=['is_active', 'updated_by', 'updated_at'])
            messages.success(
                request,
                'Exchange rate activated successfully.' if new_active else 'Exchange rate deactivated successfully.',
            )
            return redirect(reverse('fx_rate_list'))

        base_code = _get_base_currency_code()
        form = ExchangeRateForm(request.POST, instance=rate, base_currency_code=base_code)
        # The currency field is disabled on the edit UI, so browsers won't submit it.
        # Disable it here too, so validation doesn't fail due to missing data.
        if 'currency' in form.fields:
            form.fields['currency'].disabled = True
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'base_currency_code': base_code, 'rate_obj': rate},
            )

        # Backend safeguard: currency cannot be changed.
        form.instance.currency = rate.currency
        form.instance.updated_by = request.user

        old_rate = ExchangeRate.objects.get(pk=rate.fx_id).exchange_rate
        form.save()

        FXRateChangeLog.objects.create(
            currency=rate.currency,
            old_rate=old_rate,
            new_rate=rate.exchange_rate,
            notes=request.POST.get('change_notes', ''),
            changed_by=request.user,
        )

        messages.success(request, 'Exchange rate updated successfully.')
        return redirect(reverse('fx_rate_list'))


class FXRateChangeLogView(LoginRequiredMixin, View):
    template_name = 'system_config/exchange_rates/fx_log.html'

    def get(self, request):
        currency_code = request.GET.get('currency', '').strip()

        qs = (
            FXRateChangeLog.objects.select_related('currency', 'changed_by')
            .order_by('-changed_at')
        )

        if currency_code:
            qs = qs.filter(currency__currency_code=currency_code)

        # Annotate delta so templates can display +/- with color.
        delta_expr = ExpressionWrapper(
            F('new_rate') - F('old_rate'),
            output_field=DecimalField(max_digits=12, decimal_places=6),
        )
        qs = qs.annotate(delta=delta_expr, delta_abs=Abs(delta_expr))

        paginator = Paginator(qs, 20)
        page_number = request.GET.get('page', 1)
        log_page = paginator.get_page(page_number)

        currencies = Currency.objects.all().order_by('name_en')

        context = {
            'fx_logs': log_page,
            'currencies': currencies,
            'selected_currency_code': currency_code,
        }
        return render(request, self.template_name, context)


class TaxCodeListView(LoginRequiredMixin, View):
    template_name = 'system_config/tax_codes/tax_code_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        tax_codes_qs = TaxCode.objects.select_related(
            'applicable_country_code'
        ).order_by('tax_code')

        if search_query:
            tax_codes_qs = tax_codes_qs.filter(
                Q(name_en__icontains=search_query)
                | Q(tax_code__icontains=search_query)
            )

        if status_filter == 'Active':
            tax_codes_qs = tax_codes_qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            tax_codes_qs = tax_codes_qs.filter(is_active=False)

        total_count = tax_codes_qs.count()
        paginator = Paginator(tax_codes_qs, 15)
        page_number = request.GET.get('page', 1)
        tax_codes_page = paginator.get_page(page_number)

        context = {
            'tax_codes': tax_codes_page,
            'search_query': search_query,
            'status_filter': status_filter,
            'total_count': total_count,
            'page_title': 'Tax Codes Master',
        }
        return render(request, self.template_name, context)


class TaxCodeCreateView(LoginRequiredMixin, View):
    template_name = 'system_config/tax_codes/tax_code_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('tax_code_list'))
        return None

    def get(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        form = TaxCodeForm(is_edit=False)
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        form = TaxCodeForm(request.POST, is_edit=False)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )
        tax_code = form.save(commit=False)
        tax_code.updated_by = request.user
        tax_code.created_by = request.user
        tax_code.save()
        messages.success(request, 'Tax code created successfully.')
        return redirect(reverse('tax_code_list'))


class TaxCodeUpdateView(LoginRequiredMixin, View):
    template_name = 'system_config/tax_codes/tax_code_form.html'

    def _require_root(self, request):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('tax_code_list'))
        return None

    def get(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        tax_code = get_object_or_404(TaxCode, pk=pk)
        form = TaxCodeForm(instance=tax_code, is_edit=True)
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': True, 'tax_code_obj': tax_code},
        )

    def post(self, request, pk):
        redirect_resp = self._require_root(request)
        if redirect_resp:
            return redirect_resp
        tax_code = get_object_or_404(TaxCode, pk=pk)
        form = TaxCodeForm(request.POST, instance=tax_code, is_edit=True)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'tax_code_obj': tax_code},
            )
        tax_code_obj = form.save(commit=False)
        tax_code_obj.tax_code = tax_code.tax_code
        tax_code_obj.updated_by = request.user
        tax_code_obj.save()
        messages.success(request, 'Tax code updated successfully.')
        return redirect(reverse('tax_code_list'))


class TaxCodeToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not getattr(request.user, 'is_root', False):
            messages.error(request, 'Access denied: root admin only.')
            return redirect(reverse('tax_code_list'))
        tax_code = get_object_or_404(TaxCode, pk=pk)
        deactivating_default = (
            tax_code.is_active
            and (tax_code.is_default_for_country or tax_code.is_international_default)
        )
        tax_code.is_active = not tax_code.is_active
        tax_code.updated_by = request.user
        tax_code.save(update_fields=['is_active', 'updated_by'])
        if deactivating_default:
            messages.warning(
                request,
                'You deactivated a default tax code. '
                'Review country/international defaults.',
            )
        messages.success(request, 'Tax code status updated successfully.')
        return redirect(reverse('tax_code_list'))


class TaxCodeDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Tax codes cannot be deleted. Deactivate instead.')
        return redirect(reverse('tax_code_list'))

    def get(self, request, pk):
        messages.error(request, 'Tax codes cannot be deleted. Deactivate instead.')
        return redirect(reverse('tax_code_list'))


class PlanListView(LoginRequiredMixin, View):
    template_name = 'subscription/plans/plan_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        plans_qs = SubscriptionPlan.objects.annotate(
            pricing_rows_count=Count('pricing_cycles')
        ).order_by('plan_name_en')

        if search_query:
            plans_qs = plans_qs.filter(plan_name_en__icontains=search_query)

        if status_filter == 'Active':
            plans_qs = plans_qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            plans_qs = plans_qs.filter(is_active=False)

        total_count = plans_qs.count()
        paginator = Paginator(plans_qs, 10)
        page_number = request.GET.get('page', 1)
        plans_page = paginator.get_page(page_number)

        return render(
            request,
            self.template_name,
            {
                'plans': plans_page,
                'search_query': search_query,
                'status_filter': status_filter,
                'total_count': total_count,
            },
        )


class PlanCreateView(LoginRequiredMixin, View):
    template_name = 'subscription/plans/plan_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        return render(
            request,
            self.template_name,
            {
                'form': SubscriptionPlanForm(),
                'is_edit': False,
                'pricing_rows': [self._empty_row(0)],
                'currencies': Currency.objects.filter(is_active=True).order_by('name_en'),
            },
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        form = SubscriptionPlanForm(request.POST)
        rows = self._extract_rows(request.POST)
        valid_rows, row_errors, duplicate_error = self._validate_rows(rows)

        has_errors = False
        if not form.is_valid():
            has_errors = True
        if not valid_rows:
            has_errors = True
            messages.error(request, 'At least one pricing cycle is required.')
        if row_errors:
            has_errors = True
        if duplicate_error:
            has_errors = True
            messages.error(request, duplicate_error)

        if has_errors:
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': False,
                    'pricing_rows': self._rows_with_errors(rows, row_errors),
                    'currencies': Currency.objects.filter(is_active=True).order_by('name_en'),
                },
            )

        plan = form.save(commit=False)
        plan.created_by = request.user
        plan.save()

        for row in valid_rows:
            PlanPricingCycle.objects.create(
                plan=plan,
                number_of_cycles=row['cleaned_data']['number_of_cycles'],
                currency=row['cleaned_data']['currency'],
                price=row['cleaned_data']['price'],
            )

        messages.success(request, 'Subscription plan created successfully.')
        return redirect(reverse('plan_detail', kwargs={'pk': plan.plan_id}))

    def _empty_row(self, index):
        return {
            'row_index': index,
            'pricing_id': '',
            'number_of_cycles': '',
            'currency': '',
            'price': '',
            'delete': False,
            'errors': [],
        }

    def _extract_rows(self, post_data):
        row_indices = set()
        for key in post_data.keys():
            if key.startswith('pricing-'):
                parts = key.split('-')
                if len(parts) >= 3 and parts[1].isdigit():
                    row_indices.add(int(parts[1]))

        rows = []
        for index in sorted(row_indices):
            prefix = f'pricing-{index}-'
            row = {
                'row_index': index,
                'pricing_id': post_data.get(prefix + 'pricing_id', '').strip(),
                'number_of_cycles': post_data.get(prefix + 'number_of_cycles', '').strip(),
                'currency': post_data.get(prefix + 'currency', '').strip(),
                'price': post_data.get(prefix + 'price', '').strip(),
                'delete': post_data.get(prefix + 'delete', '').strip() == '1',
            }
            rows.append(row)
        return rows

    def _validate_rows(self, rows):
        valid_rows = []
        row_errors = {}
        seen = set()
        duplicate_error = None

        for row in rows:
            if row.get('delete'):
                continue
            if not any([
                row.get('number_of_cycles'),
                row.get('currency'),
                row.get('price'),
            ]):
                continue

            form = PlanPricingCycleForm(
                {
                    'number_of_cycles': row.get('number_of_cycles'),
                    'currency': row.get('currency'),
                    'price': row.get('price'),
                }
            )
            if not form.is_valid():
                row_errors[row['row_index']] = form.errors
                continue

            combo = (
                form.cleaned_data['number_of_cycles'],
                form.cleaned_data['currency'].currency_code,
            )
            if combo in seen:
                duplicate_error = (
                    'Duplicate pricing row found for same cycles and currency.'
                )
                continue
            seen.add(combo)
            valid_rows.append({'row_index': row['row_index'], 'cleaned_data': form.cleaned_data})

        return valid_rows, row_errors, duplicate_error

    def _rows_with_errors(self, rows, row_errors):
        merged = []
        if not rows:
            return [self._empty_row(0)]
        for row in rows:
            row_copy = dict(row)
            errors = row_errors.get(row['row_index'])
            row_copy['errors'] = (
                [f"{k}: {', '.join(v)}" for k, v in errors.items()]
                if errors else []
            )
            merged.append(row_copy)
        return merged


class PlanDetailView(LoginRequiredMixin, View):
    template_name = 'subscription/plans/plan_detail.html'

    def get(self, request, pk):
        plan = get_object_or_404(
            SubscriptionPlan.objects.prefetch_related('pricing_cycles__currency'),
            pk=pk,
        )
        return render(
            request,
            self.template_name,
            {
                'plan': plan,
                'pricing_cycles': plan.pricing_cycles.all().order_by('number_of_cycles'),
            },
        )


class PlanUpdateView(PlanCreateView):
    template_name = 'subscription/plans/plan_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        plan = get_object_or_404(SubscriptionPlan, pk=pk)
        form = SubscriptionPlanForm(instance=plan)
        pricing_rows = []
        for idx, pricing in enumerate(
            plan.pricing_cycles.select_related('currency').all().order_by('number_of_cycles'),
            start=0,
        ):
            pricing_rows.append({
                'row_index': idx,
                'pricing_id': str(pricing.pricing_id),
                'number_of_cycles': pricing.number_of_cycles,
                'currency': pricing.currency_id,
                'price': pricing.price,
                'delete': False,
                'errors': [],
            })
        if not pricing_rows:
            pricing_rows = [self._empty_row(0)]

        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': True,
                'plan': plan,
                'pricing_rows': pricing_rows,
                'currencies': Currency.objects.filter(is_active=True).order_by('name_en'),
            },
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        plan = get_object_or_404(SubscriptionPlan, pk=pk)
        form = SubscriptionPlanForm(request.POST, instance=plan)
        rows = self._extract_rows(request.POST)
        valid_rows, row_errors, duplicate_error = self._validate_rows(rows)

        has_errors = False
        if not form.is_valid():
            has_errors = True
        if not valid_rows:
            has_errors = True
            messages.error(request, 'At least one pricing cycle is required.')
        if row_errors:
            has_errors = True
        if duplicate_error:
            has_errors = True
            messages.error(request, duplicate_error)

        if has_errors:
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': True,
                    'plan': plan,
                    'pricing_rows': self._rows_with_errors(rows, row_errors),
                    'currencies': Currency.objects.filter(is_active=True).order_by('name_en'),
                },
            )

        plan = form.save()
        existing_map = {
            str(item.pricing_id): item
            for item in plan.pricing_cycles.all()
        }
        keep_ids = set()

        for row in rows:
            if row.get('delete') and row.get('pricing_id'):
                existing = existing_map.get(row['pricing_id'])
                if existing:
                    existing.delete()
                continue
            if row.get('delete'):
                continue
            if not any([row.get('number_of_cycles'), row.get('currency'), row.get('price')]):
                continue

            cleaned = next(
                (vr['cleaned_data'] for vr in valid_rows if vr['row_index'] == row['row_index']),
                None,
            )
            if cleaned is None:
                continue

            if row.get('pricing_id'):
                existing = existing_map.get(row['pricing_id'])
                if existing:
                    existing.number_of_cycles = cleaned['number_of_cycles']
                    existing.currency = cleaned['currency']
                    existing.price = cleaned['price']
                    existing.save()
                    keep_ids.add(str(existing.pricing_id))
                    continue

            new_obj = PlanPricingCycle.objects.create(
                plan=plan,
                number_of_cycles=cleaned['number_of_cycles'],
                currency=cleaned['currency'],
                price=cleaned['price'],
            )
            keep_ids.add(str(new_obj.pricing_id))

        for pricing_id, pricing_obj in existing_map.items():
            if pricing_id not in keep_ids:
                if not any(r.get('pricing_id') == pricing_id and r.get('delete') for r in rows):
                    pricing_obj.delete()

        if not plan.pricing_cycles.exists():
            messages.error(request, 'At least one pricing cycle is required.')
            return redirect(reverse('plan_edit', kwargs={'pk': plan.plan_id}))

        messages.success(request, 'Subscription plan updated successfully.')
        return redirect(reverse('plan_detail', kwargs={'pk': plan.plan_id}))


class PlanToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        plan = get_object_or_404(SubscriptionPlan, pk=pk)
        if plan.is_active:
            # TODO Phase 6: Check active tenant subscriptions
            #               before deactivating this plan
            plan.is_active = False
            messages.success(request, 'Plan deactivated successfully.')
        else:
            plan.is_active = True
            messages.success(request, 'Plan activated successfully.')
        plan.save(update_fields=['is_active', 'updated_at'])
        return redirect(reverse('plan_list'))


class PlanDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Plans cannot be deleted. Deactivate instead.')
        return redirect(reverse('plan_list'))

    def get(self, request, pk):
        messages.error(request, 'Plans cannot be deleted. Deactivate instead.')
        return redirect(reverse('plan_list'))


class AddOnsPolicyListView(LoginRequiredMixin, View):
    template_name = 'subscription/addons/policy_list.html'

    def get(self, request):
        policies = AddOnsPricingPolicy.objects.all().order_by('-updated_at')
        return render(
            request,
            self.template_name,
            {'policies': policies},
        )


class AddOnsPolicyCreateView(LoginRequiredMixin, View):
    template_name = 'subscription/addons/policy_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': AddOnsPricingPolicyForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp

        form = AddOnsPricingPolicyForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )

        policy = form.save(commit=False)
        policy.updated_by = request.user
        policy.save()

        if policy.is_active:
            AddOnsPricingPolicy.objects.exclude(
                policy_id=policy.policy_id
            ).update(is_active=False)

        messages.success(request, 'Add-ons policy saved successfully.')
        return redirect(reverse('addons_policy_list'))


class AddOnsPolicyUpdateView(LoginRequiredMixin, View):
    template_name = 'subscription/addons/policy_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        policy = get_object_or_404(AddOnsPricingPolicy, pk=pk)
        return render(
            request,
            self.template_name,
            {
                'form': AddOnsPricingPolicyForm(instance=policy),
                'is_edit': True,
                'policy': policy,
            },
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        policy = get_object_or_404(AddOnsPricingPolicy, pk=pk)
        form = AddOnsPricingPolicyForm(request.POST, instance=policy)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'policy': policy},
            )
        policy_obj = form.save(commit=False)
        policy_obj.updated_by = request.user
        policy_obj.save()

        if policy_obj.is_active:
            AddOnsPricingPolicy.objects.exclude(
                policy_id=policy_obj.policy_id
            ).update(is_active=False)

        messages.success(request, 'Add-ons policy updated successfully.')
        return redirect(reverse('addons_policy_list'))


class AddOnsPolicyDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        policy = get_object_or_404(AddOnsPricingPolicy, pk=pk)
        if policy.is_active:
            messages.error(request, 'Active policy cannot be deleted. Deactivate first.')
            return redirect(reverse('addons_policy_list'))
        messages.error(request, 'Policies cannot be deleted. Deactivate instead.')
        return redirect(reverse('addons_policy_list'))

    def get(self, request, pk):
        return self.post(request, pk)


class PromoCodeListView(LoginRequiredMixin, View):
    template_name = 'subscription/promo/promo_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'All')

        qs = PromoCode.objects.prefetch_related('applicable_plans').order_by('-created_at')
        if search_query:
            qs = qs.filter(code__icontains=search_query)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        paginator = Paginator(qs, 15)
        page_number = request.GET.get('page', 1)
        promo_page = paginator.get_page(page_number)

        now = timezone.now()
        return render(
            request,
            self.template_name,
            {
                'promo_codes': promo_page,
                'search_query': search_query,
                'status_filter': status_filter,
                'now': now,
            },
        )


class PromoCodeCreateView(LoginRequiredMixin, View):
    template_name = 'subscription/promo/promo_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': PromoCodeForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = PromoCodeForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )
        promo = form.save(commit=False)
        promo.code = promo.code.upper().strip()
        promo.created_by = request.user
        promo.current_uses = 0
        promo.save()
        form.save_m2m()
        messages.success(request, 'Promo code created successfully.')
        return redirect(reverse('promo_code_list'))


class PromoCodeUpdateView(LoginRequiredMixin, View):
    template_name = 'subscription/promo/promo_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        promo = get_object_or_404(PromoCode, pk=pk)
        form = PromoCodeForm(instance=promo)
        form.fields['code'].disabled = True
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': True, 'promo': promo},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        promo = get_object_or_404(PromoCode, pk=pk)
        form = PromoCodeForm(request.POST, instance=promo)
        form.fields['code'].disabled = True
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'promo': promo},
            )
        promo_obj = form.save(commit=False)
        promo_obj.code = promo.code
        promo_obj.current_uses = promo.current_uses
        promo_obj.save()
        form.save_m2m()
        messages.success(request, 'Promo code updated successfully.')
        return redirect(reverse('promo_code_list'))


class PromoCodeToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        promo = get_object_or_404(PromoCode, pk=pk)
        promo.is_active = not promo.is_active
        promo.save(update_fields=['is_active'])
        messages.success(request, 'Promo code status updated successfully.')
        return redirect(reverse('promo_code_list'))


class PromoCodeDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Promo codes cannot be deleted. Deactivate instead.')
        return redirect(reverse('promo_code_list'))

    def get(self, request, pk):
        messages.error(request, 'Promo codes cannot be deleted. Deactivate instead.')
        return redirect(reverse('promo_code_list'))


class BankAccountListView(LoginRequiredMixin, View):
    template_name = 'payment/bank_accounts/account_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        currency_filter = request.GET.get('currency', '').strip()
        status_filter = request.GET.get('status', 'All')

        qs = BankAccount.objects.select_related('currency').order_by('bank_name')
        if search_query:
            qs = qs.filter(
                Q(bank_name__icontains=search_query) | Q(iban_number__icontains=search_query)
            )
        if currency_filter:
            qs = qs.filter(currency_id=currency_filter)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        paginator = Paginator(qs, 15)
        accounts = paginator.get_page(request.GET.get('page', 1))

        return render(
            request,
            self.template_name,
            {
                'accounts': accounts,
                'search_query': search_query,
                'currency_filter': currency_filter,
                'status_filter': status_filter,
                'currencies': Currency.objects.filter(is_active=True).order_by('name_en'),
            },
        )


class BankAccountCreateView(LoginRequiredMixin, View):
    template_name = 'payment/bank_accounts/account_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': BankAccountForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = BankAccountForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )
        account = form.save(commit=False)
        account.iban_number = account.iban_number.upper().replace(' ', '').strip()
        account.created_by = request.user
        account.save()
        messages.success(request, 'Bank account created successfully.')
        return redirect(reverse('bank_account_list'))


class BankAccountUpdateView(LoginRequiredMixin, View):
    template_name = 'payment/bank_accounts/account_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        account = get_object_or_404(BankAccount, pk=pk)
        return render(
            request,
            self.template_name,
            {'form': BankAccountForm(instance=account), 'is_edit': True, 'account': account},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        account = get_object_or_404(BankAccount, pk=pk)
        form = BankAccountForm(request.POST, instance=account)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'account': account},
            )
        obj = form.save(commit=False)
        obj.iban_number = obj.iban_number.upper().replace(' ', '').strip()
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Bank account updated successfully.')
        return redirect(reverse('bank_account_list'))


class BankAccountToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        account = get_object_or_404(BankAccount, pk=pk)
        if account.is_active:
            # TODO Phase 8: Check if account is linked to active
            #               Payment Methods before deactivating
            account.is_active = False
            messages.success(request, 'Bank account deactivated successfully.')
        else:
            account.is_active = True
            messages.success(request, 'Bank account activated successfully.')
        account.save(update_fields=['is_active'])
        return redirect(reverse('bank_account_list'))


class BankAccountDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Bank accounts cannot be deleted. Deactivate instead.')
        return redirect(reverse('bank_account_list'))

    def get(self, request, pk):
        messages.error(request, 'Bank accounts cannot be deleted. Deactivate instead.')
        return redirect(reverse('bank_account_list'))


GATEWAY_MASKED_CREDENTIALS_PLACEHOLDER = '{"masked":"********"}'


class PaymentGatewayListView(LoginRequiredMixin, View):
    template_name = 'payment/gateways/gateway_list.html'

    def get(self, request):
        environment_filter = request.GET.get('environment', 'All')
        status_filter = request.GET.get('status', 'All')

        qs = PaymentGateway.objects.order_by('gateway_name')
        if environment_filter in ['Test', 'Live']:
            qs = qs.filter(environment=environment_filter)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        paginator = Paginator(qs, 10)
        gateways = paginator.get_page(request.GET.get('page', 1))

        return render(
            request,
            self.template_name,
            {
                'gateways': gateways,
                'environment_filter': environment_filter,
                'status_filter': status_filter,
            },
        )


class PaymentGatewayCreateView(LoginRequiredMixin, View):
    template_name = 'payment/gateways/gateway_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': PaymentGatewayForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = PaymentGatewayForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )
        gateway = form.save(commit=False)
        gateway.created_by = request.user
        gateway.save()
        messages.success(request, 'Payment gateway created successfully.')
        return redirect(reverse('gateway_list'))


class PaymentGatewayUpdateView(LoginRequiredMixin, View):
    template_name = 'payment/gateways/gateway_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(PaymentGateway, pk=pk)
        form = PaymentGatewayForm(instance=gateway)
        form.initial['credentials_payload'] = GATEWAY_MASKED_CREDENTIALS_PLACEHOLDER
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'is_edit': True,
                'gateway': gateway,
                'masked_placeholder': GATEWAY_MASKED_CREDENTIALS_PLACEHOLDER,
            },
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(PaymentGateway, pk=pk)
        post_data = request.POST.copy()
        raw_payload = (post_data.get('credentials_payload') or '').strip()

        # Keep existing credentials when user keeps masked placeholder.
        if raw_payload == GATEWAY_MASKED_CREDENTIALS_PLACEHOLDER:
            post_data['credentials_payload'] = json.dumps(gateway.credentials_payload)

        form = PaymentGatewayForm(post_data, instance=gateway)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    'form': form,
                    'is_edit': True,
                    'gateway': gateway,
                    'masked_placeholder': GATEWAY_MASKED_CREDENTIALS_PLACEHOLDER,
                },
            )
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Payment gateway updated successfully.')
        return redirect(reverse('gateway_list'))


class PaymentGatewayToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(PaymentGateway, pk=pk)
        if gateway.is_active:
            # TODO Phase 8: Check if gateway is linked to active
            #               Payment Methods before deactivating
            gateway.is_active = False
            messages.success(request, 'Payment gateway deactivated successfully.')
        else:
            gateway.is_active = True
            messages.success(request, 'Payment gateway activated successfully.')
        gateway.save(update_fields=['is_active'])
        return redirect(reverse('gateway_list'))


class PaymentGatewayDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Gateways cannot be deleted. Deactivate instead.')
        return redirect(reverse('gateway_list'))

    def get(self, request, pk):
        messages.error(request, 'Gateways cannot be deleted. Deactivate instead.')
        return redirect(reverse('gateway_list'))


class PaymentMethodListView(LoginRequiredMixin, View):
    template_name = 'payment/methods/method_list.html'

    def get(self, request):
        type_filter = request.GET.get('method_type', 'All')
        status_filter = request.GET.get('status', 'All')
        qs = PaymentMethod.objects.select_related(
            'gateway',
            'dedicated_bank_account',
        ).order_by('display_order', 'method_name_en')
        if type_filter in ['Online_Gateway', 'Offline_Bank']:
            qs = qs.filter(method_type=type_filter)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        paginator = Paginator(qs, 10)
        methods = paginator.get_page(request.GET.get('page', 1))

        return render(
            request,
            self.template_name,
            {
                'methods': methods,
                'type_filter': type_filter,
                'status_filter': status_filter,
            },
        )


class PaymentMethodCreateView(LoginRequiredMixin, View):
    template_name = 'payment/methods/method_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': PaymentMethodForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = PaymentMethodForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': False},
            )
        payment_method = form.save(commit=False)
        payment_method.created_by = request.user
        payment_method.save()
        messages.success(request, 'Payment method created successfully.')
        return redirect(reverse('payment_method_list'))


class PaymentMethodUpdateView(LoginRequiredMixin, View):
    template_name = 'payment/methods/method_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        method = get_object_or_404(PaymentMethod, pk=pk)
        return render(
            request,
            self.template_name,
            {'form': PaymentMethodForm(instance=method), 'is_edit': True, 'method': method},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        method = get_object_or_404(PaymentMethod, pk=pk)
        form = PaymentMethodForm(request.POST, request.FILES, instance=method)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'method': method},
            )
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Payment method updated successfully.')
        return redirect(reverse('payment_method_list'))


class PaymentMethodToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        method = get_object_or_404(PaymentMethod, pk=pk)
        method.is_active = not method.is_active
        method.save(update_fields=['is_active'])
        messages.success(request, 'Payment method status updated successfully.')
        return redirect(reverse('payment_method_list'))


class PaymentMethodDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(
            request,
            'Payment methods cannot be deleted. Deactivate instead.',
        )
        return redirect(reverse('payment_method_list'))

    def get(self, request, pk):
        messages.error(
            request,
            'Payment methods cannot be deleted. Deactivate instead.',
        )
        return redirect(reverse('payment_method_list'))


class CommGatewayListView(LoginRequiredMixin, View):
    template_name = 'comm/gateways/gateway_list.html'

    def get(self, request):
        qs = CommGateway.objects.order_by('gateway_type', 'provider_name')
        paginator = Paginator(qs, 10)
        gateways = paginator.get_page(request.GET.get('page', 1))
        return render(
            request,
            self.template_name,
            {
                'gateways': gateways,
                'active_email_id': CommGateway.objects.filter(
                    gateway_type='Email', is_active=True
                ).values_list('gateway_id', flat=True).first(),
                'active_sms_id': CommGateway.objects.filter(
                    gateway_type='SMS', is_active=True
                ).values_list('gateway_id', flat=True).first(),
            },
        )


class CommGatewayCreateView(LoginRequiredMixin, View):
    template_name = 'comm/gateways/gateway_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(request, self.template_name, {'form': CommGatewayForm(), 'is_edit': False})

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = CommGatewayForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_edit': False})
        instance = form.save(commit=False)
        instance.updated_by = request.user
        instance.save()
        if instance.is_active:
            CommGateway.objects.filter(
                gateway_type=form.cleaned_data['gateway_type']
            ).exclude(gateway_id=instance.gateway_id).update(is_active=False)
        messages.success(request, 'Communication gateway saved successfully.')
        return redirect(reverse('comm_gateway_list'))


class CommGatewayUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/gateways/gateway_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(CommGateway, pk=pk)
        form = CommGatewayForm(instance=gateway)
        form.initial['password_secret'] = '********'
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': True, 'gateway': gateway},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(CommGateway, pk=pk)
        post_data = request.POST.copy()
        if (post_data.get('password_secret') or '').strip() == '********':
            post_data['password_secret'] = gateway.password_secret
        form = CommGatewayForm(post_data, instance=gateway)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'gateway': gateway},
            )
        instance = form.save(commit=False)
        instance.updated_by = request.user
        instance.save()
        if instance.is_active:
            CommGateway.objects.filter(
                gateway_type=form.cleaned_data['gateway_type']
            ).exclude(gateway_id=instance.gateway_id).update(is_active=False)
        messages.success(request, 'Communication gateway updated successfully.')
        return redirect(reverse('comm_gateway_list'))


class CommGatewayToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        gateway = get_object_or_404(CommGateway, pk=pk)
        gateway.is_active = not gateway.is_active
        gateway.updated_by = request.user
        gateway.save(update_fields=['is_active', 'updated_by', 'updated_at'])
        if gateway.is_active:
            CommGateway.objects.filter(gateway_type=gateway.gateway_type).exclude(
                gateway_id=gateway.gateway_id
            ).update(is_active=False)
        messages.success(request, 'Gateway status updated successfully.')
        return redirect(reverse('comm_gateway_list'))


class CommGatewayDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        gateway = get_object_or_404(CommGateway, pk=pk)
        if gateway.is_active:
            messages.error(request, 'Active gateway cannot be deleted. Deactivate first.')
            return redirect(reverse('comm_gateway_list'))
        messages.error(request, 'Gateways cannot be deleted. Deactivate instead.')
        return redirect(reverse('comm_gateway_list'))

    def get(self, request, pk):
        return self.post(request, pk)


class NotificationTemplateListView(LoginRequiredMixin, View):
    template_name = 'comm/templates/template_list.html'

    def get(self, request):
        search_query = request.GET.get('q', '').strip()
        channel_filter = request.GET.get('channel', 'All')
        category_filter = request.GET.get('category', 'All')
        status_filter = request.GET.get('status', 'All')

        qs = NotificationTemplate.objects.order_by('template_name')
        if search_query:
            qs = qs.filter(template_name__icontains=search_query)
        if channel_filter in ['Email', 'SMS']:
            qs = qs.filter(channel_type=channel_filter)
        if category_filter in ['Transactional', 'Promotional']:
            qs = qs.filter(category=category_filter)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)

        paginator = Paginator(qs, 15)
        templates = paginator.get_page(request.GET.get('page', 1))
        return render(
            request,
            self.template_name,
            {
                'templates_page': templates,
                'search_query': search_query,
                'channel_filter': channel_filter,
                'category_filter': category_filter,
                'status_filter': status_filter,
            },
        )


class NotificationTemplateCreateView(LoginRequiredMixin, View):
    template_name = 'comm/templates/template_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(
            request,
            self.template_name,
            {'form': NotificationTemplateForm(), 'is_edit': False},
        )

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = NotificationTemplateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_edit': False})
        obj = form.save(commit=False)
        obj.created_by = request.user
        obj.save()
        messages.success(request, 'Notification template created successfully.')
        return redirect(reverse('notif_template_list'))


class NotificationTemplateUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/templates/template_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        template_obj = get_object_or_404(NotificationTemplate, pk=pk)
        form = NotificationTemplateForm(instance=template_obj)
        return render(
            request,
            self.template_name,
            {'form': form, 'is_edit': True, 'template_obj': template_obj},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        template_obj = get_object_or_404(NotificationTemplate, pk=pk)
        form = NotificationTemplateForm(request.POST, instance=template_obj)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'template_obj': template_obj},
            )
        form.save()
        messages.success(request, 'Notification template updated successfully.')
        return redirect(reverse('notif_template_list'))


class NotificationTemplateToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        template_obj = get_object_or_404(NotificationTemplate, pk=pk)
        is_in_active_mapping = EventMapping.objects.filter(
            is_active=True,
        ).filter(
            Q(primary_template=template_obj) | Q(fallback_template=template_obj)
        ).exists()
        # TODO: EventMapping may break if template deactivated
        template_obj.is_active = not template_obj.is_active
        template_obj.save(update_fields=['is_active'])
        if is_in_active_mapping and not template_obj.is_active:
            messages.warning(
                request,
                'Template is used in active event mapping. Deactivated with caution.',
            )
        else:
            messages.success(request, 'Template status updated successfully.')
        return redirect(reverse('notif_template_list'))


class NotificationTemplateDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        messages.error(request, 'Templates cannot be deleted. Deactivate instead.')
        return redirect(reverse('notif_template_list'))

    def get(self, request, pk):
        messages.error(request, 'Templates cannot be deleted. Deactivate instead.')
        return redirect(reverse('notif_template_list'))


class EventMappingListView(LoginRequiredMixin, View):
    template_name = 'comm/events/event_list.html'

    def get(self, request):
        qs = EventMapping.objects.select_related(
            'primary_template', 'fallback_template'
        ).order_by('system_event')
        paginator = Paginator(qs, 15)
        mappings = paginator.get_page(request.GET.get('page', 1))
        configured_events = set(qs.values_list('system_event', flat=True))
        event_labels = dict(EventMapping.SYSTEM_EVENT_CHOICES)
        unmapped_events = [
            event_labels[code]
            for code, _label in EventMapping.SYSTEM_EVENT_CHOICES
            if code not in configured_events
        ]
        return render(
            request,
            self.template_name,
            {'mappings': mappings, 'unmapped_events': unmapped_events},
        )


class EventMappingCreateView(LoginRequiredMixin, View):
    template_name = 'comm/events/event_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(request, self.template_name, {'form': EventMappingForm(), 'is_edit': False})

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = EventMappingForm(request.POST)
        if form.is_valid():
            event_code = form.cleaned_data.get('system_event')
            if EventMapping.objects.filter(system_event=event_code).exists():
                form.add_error(
                    'system_event',
                    'A mapping already exists for this event. Edit it instead.',
                )
            else:
                obj = form.save(commit=False)
                obj.updated_by = request.user
                obj.save()
                messages.success(request, 'Event mapping created successfully.')
                return redirect(reverse('event_mapping_list'))
        return render(request, self.template_name, {'form': form, 'is_edit': False})


class EventMappingUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/events/event_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        mapping = get_object_or_404(EventMapping, pk=pk)
        return render(
            request,
            self.template_name,
            {'form': EventMappingForm(instance=mapping), 'is_edit': True, 'mapping': mapping},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        mapping = get_object_or_404(EventMapping, pk=pk)
        form = EventMappingForm(request.POST, instance=mapping)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'mapping': mapping},
            )
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Event mapping updated successfully.')
        return redirect(reverse('event_mapping_list'))


class EventMappingToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        mapping = get_object_or_404(EventMapping, pk=pk)
        mapping.is_active = not mapping.is_active
        mapping.updated_by = request.user
        mapping.save(update_fields=['is_active', 'updated_by', 'updated_at'])
        messages.success(request, 'Event mapping status updated successfully.')
        return redirect(reverse('event_mapping_list'))


class PushNotificationListView(LoginRequiredMixin, View):
    template_name = 'comm/push/push_list.html'

    def get(self, request):
        trigger_mode = request.GET.get('trigger_mode', 'All')
        dispatch_status = request.GET.get('dispatch_status', 'All')
        qs = PushNotification.objects.order_by('-created_at')
        if trigger_mode in ['Manual_Broadcast', 'System_Event']:
            qs = qs.filter(trigger_mode=trigger_mode)
        if dispatch_status in ['Draft', 'Scheduled', 'Completed']:
            qs = qs.filter(dispatch_status=dispatch_status)
        paginator = Paginator(qs, 15)
        push_items = paginator.get_page(request.GET.get('page', 1))
        return render(
            request,
            self.template_name,
            {
                'push_items': push_items,
                'trigger_mode_filter': trigger_mode,
                'dispatch_status_filter': dispatch_status,
            },
        )


class PushNotificationCreateView(LoginRequiredMixin, View):
    template_name = 'comm/push/push_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(request, self.template_name, {'form': PushNotificationForm(), 'is_edit': False})

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = PushNotificationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_edit': False})
        obj = form.save(commit=False)
        obj.created_by = request.user
        # TODO Phase 11: Queue actual FCM push dispatch here
        obj.save()
        messages.success(request, 'Push notification created successfully.')
        return redirect(reverse('push_notif_list'))


class PushNotificationUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/push/push_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        push_item = get_object_or_404(PushNotification, pk=pk)
        if push_item.dispatch_status == 'Completed':
            messages.error(request, 'Completed push notifications cannot be edited.')
            return redirect(reverse('push_notif_list'))
        return render(
            request,
            self.template_name,
            {'form': PushNotificationForm(instance=push_item), 'is_edit': True, 'push_item': push_item},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        push_item = get_object_or_404(PushNotification, pk=pk)
        if push_item.dispatch_status == 'Completed':
            messages.error(request, 'Completed push notifications cannot be edited.')
            return redirect(reverse('push_notif_list'))
        form = PushNotificationForm(request.POST, instance=push_item)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'push_item': push_item},
            )
        form.save()
        messages.success(request, 'Push notification updated successfully.')
        return redirect(reverse('push_notif_list'))


class SystemBannerListView(LoginRequiredMixin, View):
    template_name = 'comm/banners/banner_list.html'

    def get(self, request):
        severity_filter = request.GET.get('severity', 'All')
        status_filter = request.GET.get('status', 'All')
        qs = SystemBanner.objects.order_by('-valid_from')
        if severity_filter in ['Info', 'Warning', 'Critical']:
            qs = qs.filter(severity=severity_filter)
        if status_filter == 'Active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'Inactive':
            qs = qs.filter(is_active=False)
        paginator = Paginator(qs, 10)
        banners = paginator.get_page(request.GET.get('page', 1))
        return render(
            request,
            self.template_name,
            {
                'banners': banners,
                'severity_filter': severity_filter,
                'status_filter': status_filter,
            },
        )


class SystemBannerCreateView(LoginRequiredMixin, View):
    template_name = 'comm/banners/banner_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(request, self.template_name, {'form': SystemBannerForm(), 'is_edit': False})

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = SystemBannerForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_edit': False})
        form.save()
        messages.success(request, 'System banner created successfully.')
        return redirect(reverse('banner_list'))


class SystemBannerUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/banners/banner_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        banner = get_object_or_404(SystemBanner, pk=pk)
        return render(
            request,
            self.template_name,
            {'form': SystemBannerForm(instance=banner), 'is_edit': True, 'banner': banner},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        banner = get_object_or_404(SystemBanner, pk=pk)
        form = SystemBannerForm(request.POST, instance=banner)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'banner': banner},
            )
        form.save()
        messages.success(request, 'System banner updated successfully.')
        return redirect(reverse('banner_list'))


class SystemBannerToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        banner = get_object_or_404(SystemBanner, pk=pk)
        banner.is_active = not banner.is_active
        banner.save(update_fields=['is_active'])
        messages.success(request, 'System banner status updated successfully.')
        return redirect(reverse('banner_list'))


class InternalAlertRouteListView(LoginRequiredMixin, View):
    template_name = 'comm/alerts/alert_list.html'

    def get(self, request):
        qs = InternalAlertRoute.objects.select_related('notify_role').order_by('trigger_event')
        paginator = Paginator(qs, 10)
        routes = paginator.get_page(request.GET.get('page', 1))
        return render(request, self.template_name, {'routes': routes})


class InternalAlertRouteCreateView(LoginRequiredMixin, View):
    template_name = 'comm/alerts/alert_form.html'

    def get(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        return render(request, self.template_name, {'form': InternalAlertRouteForm(), 'is_edit': False})

    def post(self, request):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        form = InternalAlertRouteForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_edit': False})
        form.save()
        messages.success(request, 'Alert route created successfully.')
        return redirect(reverse('alert_route_list'))


class InternalAlertRouteUpdateView(LoginRequiredMixin, View):
    template_name = 'comm/alerts/alert_form.html'

    def get(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        route = get_object_or_404(InternalAlertRoute, pk=pk)
        return render(
            request,
            self.template_name,
            {'form': InternalAlertRouteForm(instance=route), 'is_edit': True, 'route': route},
        )

    def post(self, request, pk):
        redirect_resp = _require_root_or_redirect(request)
        if redirect_resp:
            return redirect_resp
        route = get_object_or_404(InternalAlertRoute, pk=pk)
        form = InternalAlertRouteForm(request.POST, instance=route)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {'form': form, 'is_edit': True, 'route': route},
            )
        form.save()
        messages.success(request, 'Alert route updated successfully.')
        return redirect(reverse('alert_route_list'))


class InternalAlertRouteToggleStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        route = get_object_or_404(InternalAlertRoute, pk=pk)
        route.is_active = not route.is_active
        route.save(update_fields=['is_active'])
        messages.success(request, 'Alert route status updated successfully.')
        return redirect(reverse('alert_route_list'))


class CommLogListView(LoginRequiredMixin, View):
    template_name = 'comm/logs/comm_log_list.html'

    def get(self, request):
        query = request.GET.get('q', '').strip()
        channel_filter = request.GET.get('channel', 'All')
        status_filter = request.GET.get('status', 'All')
        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()

        qs = CommLog.objects.order_by('-dispatched_at')
        if query:
            qs = qs.filter(recipient__icontains=query)
        if channel_filter in ['Email', 'SMS', 'Push']:
            qs = qs.filter(channel_type=channel_filter)
        if status_filter in ['Sent', 'Failed', 'Bounced']:
            qs = qs.filter(delivery_status=status_filter)
        if date_from:
            parsed_from = parse_date(date_from)
            if parsed_from:
                qs = qs.filter(dispatched_at__date__gte=parsed_from)
        if date_to:
            parsed_to = parse_date(date_to)
            if parsed_to:
                qs = qs.filter(dispatched_at__date__lte=parsed_to)

        paginator = Paginator(qs, 20)
        logs = paginator.get_page(request.GET.get('page', 1))
        return render(
            request,
            self.template_name,
            {
                'logs': logs,
                'search_query': query,
                'channel_filter': channel_filter,
                'status_filter': status_filter,
                'date_from': date_from,
                'date_to': date_to,
            },
        )
