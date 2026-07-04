from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Role, UserProfile


class UserProfileInline(admin.StackedInline):
    fk_name = "user"
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ("theme", "bio", "avatar", "last_activity", "is_locked", "failed_login_count")
    readonly_fields = ("last_activity", "failed_login_count")


class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "modified_at")
