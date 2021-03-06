from django.contrib import admin

from .models import Profile, CoolDown, Server, JoinCode, Guild, Gamble, Hunt


@admin.register(JoinCode)
class JoinCodeAdmin(admin.ModelAdmin):
    list_filter = ("claimed",)
    list_display = ("code", "claimed")


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    search_fields = ("code__id", "name", "id")


@admin.register(Guild)
class GuildAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    search_fields = ("last_known_nickname", "uid")
    list_display = ("last_known_nickname", "uid", "player_guild")
    list_filter = ("notify", "player_guild")


@admin.register(CoolDown)
class CoolDownAdmin(admin.ModelAdmin):
    search_fields = ("profile__last_known_nickname", "type")
    list_filter = ("type",)


@admin.register(Gamble)
class GambleAdmin(admin.ModelAdmin):
    list_display = ["event", "created"]
    search_fields = ("game", "outcome", "profile__last_known_nickname")
    list_filter = ("game", "outcome")

    def event(self, obj):
        return str(obj)


@admin.register(Hunt)
class HuntAdmin(admin.ModelAdmin):
    list_display = ["player", "target", "money", "xp", "loot", "created"]
    search_fields = ["profile__last_known_nickname", "target"]
    list_filter = ["loot"]

    def player(self, obj):
        if not obj.profile:
            return "Anonymous"
        return obj.profile.last_known_nickname
