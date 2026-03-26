from django.contrib import messages
from django.contrib.sessions.models import Session
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import TemplateView

from .auth_helpers import (
    check_brute_force,
    create_auth_token,
    get_security_settings,
    log_access,
    record_failed_attempt,
    reset_failed_attempts,
)
from .forms import (
    AdminUserForm,
    CountryForm,
    CurrencyForm,
    ForgotPasswordForm,
    LoginForm,
    RoleForm,
    SetPasswordForm,
)
from .models import AccessLog, AdminAuthToken, AdminUser, Country, Currency, Role


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
