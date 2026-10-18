from django.contrib import admin
from .models import GameRound
from .models import AlertRule, AlertDestination, AlertEvaluation, AlertOccurrence, AlertDelivery, AlertRuntime

@admin.register(GameRound)
class GameRoundAdmin(admin.ModelAdmin):
    list_display = ("game_no","game_type","has_pre","has_winner","winning_number","bet_users","updated_at")
    search_fields = ("game_no",)
    list_filter = ("has_pre","has_winner","game_type")


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'series', 'mode', 'threshold', 'window', 'revision', 'enabled', 'min_plan_rank')
    list_filter = ('series', 'mode', 'enabled', 'session_only')
    search_fields = ('key', 'title')
    readonly_fields = ('revision',)


@admin.register(AlertDestination)
class AlertDestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'chat_id', 'plan_rank', 'enabled', 'expires_at', 'send_results')
    list_filter = ('enabled', 'plan_rank')


class FrozenAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AlertEvaluation)
class AlertEvaluationAdmin(FrozenAdmin):
    list_display = ('game_no', 'observed_at', 'captured_at')


@admin.register(AlertOccurrence)
class AlertOccurrenceAdmin(FrozenAdmin):
    list_display = ('rule_key', 'evaluation', 'is_activation')
    list_filter = ('is_activation', 'rule_key')


@admin.register(AlertDelivery)
class AlertDeliveryAdmin(FrozenAdmin):
    list_display = ('id', 'kind', 'destination', 'status', 'attempts', 'message_id', 'created_at')
    list_filter = ('status', 'kind')


admin.site.register(AlertRuntime, FrozenAdmin)
