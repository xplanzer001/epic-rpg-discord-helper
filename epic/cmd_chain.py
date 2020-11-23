import re
import pytz
import discord
import datetime
import functools

from asgiref.sync import sync_to_async
from pipeline import execution_pipeline

from django.forms.models import model_to_dict

from epic.models import CoolDown, Profile, Server, JoinCode
from epic.utils import tokenize


class RpgCdMessage:
    color = 0x8C8A89
    title = None

    def __init__(self, msg, title=None):
        self.msg = msg
        if title:
            self.title = title

    def to_embed(self):
        kwargs = {"color": self.color, "description": self.msg}
        if self.title:
            kwargs["title"] = self.title
        return discord.Embed(**kwargs)


class ErrorMessage(RpgCdMessage):
    title = "Error"
    color = 0xEB4034


class NormalMessage(RpgCdMessage):
    color = 0x4381CC


class HelpMessage(RpgCdMessage):
    title = "Help"


class SuccessMessage(RpgCdMessage):
    color = 0x628F47


def params_as_args(func):
    arg_names = ["client", "tokens", "message", "server", "profile", "msg", "help"]

    @functools.wraps(func)
    def wrapper(params):
        if params["msg"] or params.get("error", None):
            # short-circuit to prevent running
            # the rest of the command chain
            return params
        # if they are using commands, we want to go ahead and
        # make them a profile.
        if params["profile"] is None:
            message, server, tokens, help = params["message"], params["server"], params["tokens"], params["help"]
            if server is not None:
                profile, _ = Profile.objects.get_or_create(
                    uid=message.author.id,
                    defaults={
                        "last_known_nickname": message.author.name,
                        "server": server,
                        "channel": message.channel.id,
                    },
                )
                params["profile"] = profile
            elif not help and tokens and tokens[0] not in {"help", "register"}:
                params["msg"] = ErrorMessage(
                    "You can only use `help` and `register` commands until"
                    f"{message.channel.guild.name} has used a join code."
                )
        args = [params.get(arg_name, None) for arg_name in arg_names]
        res = func(*args)
        if not res:
            return params
        params.update(res)
        return params

    return wrapper


@params_as_args
def _help(client, tokens, message, server, profile, msg, help=None, error=None):
    """

    Call `help` on an available command to see it's usage. Example:
    `rcd help register`
    `rcd h register`
    `rcd h notify`

    Available Commands:
        • `rcd register`
        • `rcd profile|p [<profile_command>]`
        • `rcd on`
        • `rcd off`
        • `rcd timezone|tz <timezone>`
        • `rcd <command_type> on|off`
        • `rcd [notify|n] <command_type> on|off`
        • `rcd whocan|w <command_type>`
        • `rcd cd` or `rcd`

    This bot attempts to determine the cooldowns of your EPIC RPG commands
    and will notify you when it thinks your commands are available again.
    Cooldowns are determined in two ways:
        • The cooldown duration for an observed EPIC RPG command is added to the current time. A notification is scheduled for this time.
        • The output of `rpg cd` is extracted and used to schedule notifications for all commands currently on cooldown.
    """
    if not tokens:
        # default command is now cd instead of help
        return {"tokens": ["cd"]}
    if tokens[0] not in {"help", "h"}:
        return
    if len(tokens) == 1:
        return {"msg": HelpMessage(_help.__doc__)}
    return {"help": True, "tokens": tokens[1:]}


@params_as_args
def cd(client, tokens, message, server, profile, msg, help=None):
    """
    Display when your cooldowns are expected to be done.
    Usage:
        • `rcd cd [<cooldown_types> [...<cooldown_types>]]`
    Example:
        • `rcd cd`
        • `rcd`
        • `rcd daily weekly`
    """
    implicit_invocation = False
    if tokens[0] in CoolDown.COOLDOWN_MAP or re.match(r"<@!?(?P<user_id>\d+)>", tokens[0]):
        # allow implicit invocation of cd
        tokens, implicit_invocation = ["cd", *tokens], True
    nickname = message.author.name
    cooldown_filter = lambda x: True  # show all filters by default
    if tokens[0] != "cd":
        return None
    if help and len(tokens) == 1:
        return {"msg": HelpMessage(cd.__doc__)}
    elif len(tokens) > 1:
        maybe_user_id = re.match(r"<@!?(?P<user_id>\d+)>", tokens[1])
        if maybe_user_id:
            user_id = int(
                maybe_user_id.groupdict()["user_id"],
            )
            profile, _ = Profile.objects.get_or_create(
                uid=user_id,
                defaults={
                    "last_known_nickname": client.get_user(user_id).name,
                    "server": server,
                    "channel": message.channel.id,
                },
            )
            nickname = profile.last_known_nickname
        # means there are cooldown type arguments to filter on
        if maybe_user_id and len(tokens) > 2:
            cooldown_filter = lambda x: x in set(tokens[2:])
        else:
            cooldown_filter = lambda x: x in set(tokens[1:])

    profile_tz = pytz.timezone(profile.timezone)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    default = datetime.datetime(1790, 1, 1, tzinfo=datetime.timezone.utc)
    msg = ""
    cooldowns = {
        _cd[0]: _cd[1]
        for _cd in CoolDown.objects.filter(profile_id=profile.pk).order_by("after").values_list("type", "after")
    }
    all_cooldown_types = sorted(
        filter(cooldown_filter, map(lambda c: c[0], CoolDown.COOLDOWN_TYPE_CHOICES)),
        key=lambda x: cooldowns[x] if x in cooldowns else default,
    )
    for cooldown_type in all_cooldown_types:
        after = cooldowns.get(cooldown_type, None)
        if after:
            if after > now:
                cooldown_after = cooldowns[cooldown_type].astimezone(profile_tz)
                msg += f":clock2: `{cooldown_type:12} {cooldown_after.strftime('%I:%M:%S %p, %m/%d'):>20}`\n"
        else:
            msg += f":white_check_mark: `{cooldown_type:12} {'Ready!':>20}` \n"
    if not msg:
        msg = "Please use `rpg cd` or an EPIC RPG command to populate your cooldowns.\n"
    return {"msg": NormalMessage(msg, title=f"**{nickname}'s** Cooldowns ({profile.timezone})")}


@params_as_args
def register(client, tokens, message, server, profile, msg, help=None, error=None):
    """
        Register your server for use with Epic Reminder.
    Compute resources are limited, so invite codes will be doled out sparingly.
    Example:
        • `rcd register asdf` attempts to register the server using the join code `asdf`
    """
    if tokens[0] != "register":
        return None
    if help or len(tokens) == 1:
        return {"msg": HelpMessage(register.__doc__)}
    if server:
        return {"msg": NormalMessage(f"{message.channel.guild.name} has already joined! Hello again!", title="Hi!")}
    if len(tokens) > 1:
        cmd, *args = tokens
    else:
        cmd, args = tokens[0], ()
    if not args:
        return {"msg": ErrorMessage("You must provide a join code to register.", title="Registration Error")}
    join_code = JoinCode.objects.filter(code=args[0], claimed=False).first()
    if not join_code:
        return {"msg": ErrorMessage("That is not a valid Join Code.", title="Invalid Join Code")}
    server = Server.objects.create(id=message.channel.guild.id, name=message.channel.guild.name, code=join_code)
    join_code.claim()
    return {"msg": SuccessMessage(f"Welcome {message.channel.guild.name}!", title="Welcome!")}


@params_as_args
def _profile(client, tokens, message, server, profile, msg, help=None):
    """
    When called without any arguments, e.g. `rcd profile` this will display
    profile-related information. Otherwise, it will treat your input as a profile related sub-command.

    Available Commands:
        • `rcd profile|p`
        • `rcd profile|p timezone|tz <timezone>`
        • `rcd profile|p on|off`
        • `rcd profile|p [notify|n] <cooldown_type> on|off`
    Examples:
        • `rcd profile` Displays your profile information
        • `rcd p tz <timezone>` Sets your timezone to the provided timezone.
        • `rcd p on` Enables notifications for your profile.
        • `rcd p notify hunt on` Turns on hunt notifications for your profile.
        • `rcd p hunt on` Turns on hunt notifications for your profile.
    """
    if tokens[0] not in {"profile", "p"}:
        return None
    if help and len(tokens) == 1:
        return {"msg": HelpMessage(_profile.__doc__)}
    elif len(tokens) > 1:
        # allow other commands to be namespaced by profile if that's how the user calls it
        if tokens[1] in {
            *("timezone", "tz"),
            *("notify", "n"),
            "on",
            "off",
            # allow implicit command type commands to be namespaced by `rcd p`
            *CoolDown.COOLDOWN_MAP.keys(),
        }:
            return {"tokens": tokens[1:]}
        return {"error": 1}
    msg = ""
    msg += f"`{'nickname':12}` =>   {profile.last_known_nickname}\n"
    msg += f"`{'timezone':12}` =>   {profile.timezone}\n"
    for k, v in model_to_dict(profile).items():
        if isinstance(v, bool):
            msg += f"`{k:12}` =>   {':ballot_box_with_check:' if v else ':x:'}\n"
    return {"msg": NormalMessage(msg)}


@params_as_args
def notify(client, tokens, message, server, profile, msg, help=None):
    """
        Manage your notification settings. Here you can specify which types of
    epic rpg commands you would like to receive reminders for. For example, you can
    enable or disable showing a reminder for when `rpg hunt` should be available. All reminders
    are enabled by defailt. Example usage:
        • `rcd notify hunt on` Will turn on cd notifcations for `rpg hunt`.
        • `rcd daily on` Will turn on cd notifcations for `rpg hunt`.
        • `rcd n hunt off` Will turn off notifications for `rpg hunt`
        • `rcd n weekly on` Will turn on notifications for `rpg weekly`
        • `rcd n all off` Will turn off all notifications (but `profile.notify == True`)

    Command Types:
        • `all`
        • `daily`
        • `weekly`
        • `lootbox`
        • `vote`
        • `hunt`
        • `adventure`
        • `training`
        • `duel`
        • `quest`
        • `work` (chop, mine, fish, etc.)
        • `horse`
        • `arena`
        • `dungeon`
    """
    if (tokens[0] in CoolDown.COOLDOWN_MAP or tokens[0] == "all") and tokens[-1] in {"on", "off"}:
        # allow implicit invocation of notify
        tokens = ["notify", *tokens]
        # make sure all passed tokens are valid cooldown type
        for token in {*tokens[1:-1]}:
            if token not in CoolDown.COOLDOWN_MAP and token != "all":
                return {"error": 1}
    if tokens[0] not in {"notify", "n"} or len(tokens) == 2:
        return None
    if help or len(tokens) == 1:
        return {"msg": HelpMessage(notify.__doc__)}
    _, command_type, toggle = tokens
    if (command_type in CoolDown.COOLDOWN_MAP or command_type == "all") and toggle in {"on", "off"}:
        on = toggle == "on"
        if command_type == "all":
            kwargs = {command_name: on for _, command_name in CoolDown.COOLDOWN_TYPE_CHOICES}
        else:
            # "work" is stored as "mine" in the database
            command_type = "work" if command_type == "mine" else command_type
            kwargs = {command_type: on}
        profile.update(last_known_nickname=message.author.name, **kwargs)
        if not profile.notify:
            return {
                "msg": NormalMessage(
                    f"Notifications for `{command_type}` are now {toggle} for **{message.author.name}** "
                    "but you will need to turn on notifications before you can receive any. "
                    "Try `rcd on` to start receiving notifcations."
                )
            }
        return {
            "msg": SuccessMessage(
                f"Notifications for **{command_type}** are now **{toggle}** for **{message.author.name}**."
            )
        }


@params_as_args
def on(client, tokens, message, server, profile, msg, help=None):
    """
    Toggle your profile notifications **on**. Example:
      • `rcd on`
    """
    if tokens[0] != "on":
        return None
    if help and len(tokens) == 1:
        return {"msg": HelpMessage(on.__doc__)}
    elif len(tokens) != 1:
        return {"error": 1}

    profile.update(notify=True)
    return {"msg": SuccessMessage(f"Notifications are now **on** for **{message.author.name}**.")}


@params_as_args
def off(client, tokens, message, server, profile, msg, help=None):
    """
    Toggle your profile notifications **off**. Example:
      • `rcd off`
    """
    if tokens[0] != "off":
        return None
    if help and len(tokens) == 1:
        return {"msg": HelpMessage(off.__doc__)}
    elif len(tokens) != 1:
        return {"error": 1}

    profile.update(notify=False)
    return {"msg": SuccessMessage(f"Notifications are now **off** for **{message.author.name}**.")}


@params_as_args
def timezone(client, tokens, message, server, profile, msg, help=None):
    """
    Set your timezone. Example:
      • `rcd timezone <timezone>` Sets your timezone to the provided timzone.
        (This only effects the time displayed in `rcd cd`; notification functionality
         is not effected.)
    """
    command = tokens[0]
    if command not in {"timezone", "tz"}:
        return None
    if len(tokens) == 2:
        # need case sensitive tokens to get correct timezone name,
        # need case insensitive tokens to get relative position in of
        # tz|timezone token from user input
        tokens = tokenize(message.content[:250], preserve_case=True)[1:]
        itokens = tokenize(message.content[:250], preserve_case=False)[1:]
        # get the case-preserved token which follows tz|timezone in the token list
        tz = tokens[itokens.index(command) + 1]
        if tz not in set(map(lambda x: x[0], Profile.TIMEZONE_CHOICES)):
            return {"msg": ErrorMessage(f"{tz} is not a valid timezone.")}
        else:
            profile.update(timezone=tz)
            return {"msg": SuccessMessage(f"**{message.author.name}'s** timezone has been set to **{tz}**.")}


@params_as_args
def whocan(client, tokens, message, server, profile, msg, help=None):
    """
    Determine who in your server can use a particular command. Example:
      • `rcd whocan dungeon`
      • `rcd w dungeon`
    """
    if tokens[0] not in {"whocan", "w"}:
        return None
    if help or len(tokens) == 1:
        return {"msg": HelpMessage(whocan.__doc__)}

    rpg_command = " ".join(tokens[1:])
    if tokens[1] not in CoolDown.COMMAND_RESOLUTION_MAP:
        return {
            "msg": ErrorMessage(
                "`rcd whocan` should work with any group command "
                "that you can use with EPIC RPG. If you think this "
                "error is a mistake, let me know.",
                title=f"Invalid Command Type `{rpg_command}`",
            )
        }

    cooldown_type_func = CoolDown.COMMAND_RESOLUTION_MAP[tokens[1]]
    if len(tokens) > 2:
        cooldown_type = cooldown_type_func(" ".join(tokens[2:]))
    else:
        cooldown_type = cooldown_type_func(None)

    ats = [
        f"<@{uid}>"
        for uid in set(
            Profile.objects.exclude(uid=profile.uid)
            .exclude(cooldown__type=cooldown_type)
            .filter(server_id=message.channel.guild.id)
            .values_list("uid", flat=True)
        )
    ]
    if ats:
        msg = f"All of these players can `{rpg_command}`: \n\n" + "\n\t".join(ats)
        msg += f"\n\nExample: \n\n```rpg {rpg_command} {' '.join(ats)}\n\n```"
        return {"msg": SuccessMessage(msg, title=f"They can **{rpg_command.title()}**")}
    return {"msg": NormalMessage("Sorry, no one can do that right now.")}


command_pipeline = execution_pipeline(
    pre=[
        _help,  # needs to be first to pass "help" param to those that follow
        whocan,
        # most commands that follow can be invoked as profile subcommand
        _profile,
        notify,  # notify must be before cd so `rcd hunt on` works
        # cd allows arbitrary arguments so it must follow
        # all other commands that can be invoked implicitly
        cd,
        on,
        off,
        timezone,
        register,  # called rarely, should be last.
    ],
)


@sync_to_async
@command_pipeline
def handle_rpcd_message(client, tokens, message, server, profile, msg, help=None, error=None):
    if (error and not isinstance(error, str)) or not msg:
        original_tokens = tokenize(message.content[:250], preserve_case=True)
        return ErrorMessage(f"`{' '.join(original_tokens)}` could not be parsed as a valid command.")
    elif error:
        return ErrorMessage(error)
    return msg
