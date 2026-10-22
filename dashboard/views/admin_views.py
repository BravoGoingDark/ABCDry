from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _

from ..forms import UserCreateForm
from ..models import Region, UserProfile
from .utils import _is_admin_user, _deny_admin_access


@login_required(login_url='dashboard:login')
def admin_panel(request):
    """Admin user management panel"""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    users = User.objects.all().select_related('profile').order_by('-date_joined')

    if request.method == 'POST':
        form = UserCreateForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, _('User "{}" created successfully!').format(user.username))
            return redirect('dashboard:admin_panel')
    else:
        form = UserCreateForm(user=request.user)

    context = {
        'form': form,
        'users': users,
    }
    return render(request, 'dashboard/admin_panel.html', context)


@login_required(login_url='dashboard:login')
def admin_edit_user(request, user_id):
    """Edit user role and region assignment"""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    target_user = get_object_or_404(User, pk=user_id)
    profile = target_user.profile

    if request.method == 'POST':
        role = request.POST.get('role')
        region_id = request.POST.get('region')

        if role in dict(UserProfile.ROLE_CHOICES):
            profile.role = role
        if region_id:
            profile.region_id = region_id
        else:
            profile.region = None
        profile.save()

        messages.success(request, _('User profile updated!'))
        return redirect('dashboard:admin_panel')

    context = {
        'target_user': target_user,
        'regions': Region.objects.all(),
        'role_choices': UserProfile.ROLE_CHOICES,
    }
    return render(request, 'dashboard/admin_edit_user.html', context)


@login_required(login_url='dashboard:login')
@require_http_methods(["POST"])
def admin_delete_user(request, user_id):
    """Delete a user (superadmin only)."""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    target_user = get_object_or_404(User, pk=user_id)
    if target_user == request.user:
        messages.error(request, _('You cannot delete your own account.'))
        return redirect('dashboard:admin_panel')

    target_user.delete()
    messages.success(request, _('User deleted successfully.'))
    return redirect('dashboard:admin_panel')
