import re
import pytz
import datetime
import itertools

from asgiref.sync import sync_to_async

from django.db import models
from django.utils import timezone

from .mixins import UpdateAble
from .utils import tokenize
from .managers import ProfileManager, GamblingStatsManager, HuntManager


class JoinCode(models.Model):
    code = models.CharField(max_length=256)
    claimed = models.BooleanField(default=False)

    def claim(self):
        self.claimed = True
        self.save()

    def __str__(self):
        return self.code


class Server(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True)
    name = models.CharField(max_length=250)
    code = models.OneToOneField(JoinCode, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}({self.id}) joined with {self.code}"


class Guild(UpdateAble, models.Model):
    name = models.CharField(max_length=50, primary_key=True)
    after = models.DateTimeField(null=True, blank=True)
    # player has dibbs on the next guild event
    raid_dibbs = models.ForeignKey(
        "epic.Profile", null=True, blank=True, on_delete=models.SET_NULL, related_name="has_raid_dibbs_for"
    )

    def __str__(self):
        return self.name


class Profile(UpdateAble, models.Model):
    DEFAULT_TIMEZONE = "America/Chicago"
    TIMEZONE_CHOICES = tuple(zip(pytz.common_timezones, pytz.common_timezones))
    DEFAULT_TIME_FORMAT, MAX_TIME_FORMAT_LENGTH = "%I:%M:%S %p, %m/%d", 50
    user_id_regex = re.compile(r"<@!?(?P<user_id>\d+)>")

    uid = models.CharField(max_length=50, primary_key=True)
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    channel = models.PositiveBigIntegerField()
    player_guild = models.ForeignKey(Guild, on_delete=models.SET_NULL, null=True, blank=True)
    last_known_nickname = models.CharField(max_length=250)
    timezone = models.CharField(
        choices=TIMEZONE_CHOICES, max_length=max(map(len, pytz.common_timezones)), default=DEFAULT_TIMEZONE
    )
    time_format = models.CharField(max_length=MAX_TIME_FORMAT_LENGTH, default=DEFAULT_TIME_FORMAT)
    notify = models.BooleanField(default=False)
    daily = models.BooleanField(default=True)
    weekly = models.BooleanField(default=True)
    lootbox = models.BooleanField(default=True)
    vote = models.BooleanField(default=True)
    hunt = models.BooleanField(default=True)
    adventure = models.BooleanField(default=True)
    training = models.BooleanField(default=True)
    duel = models.BooleanField(default=True)
    quest = models.BooleanField(default=True)
    work = models.BooleanField(default=True)
    horse = models.BooleanField(default=True)
    arena = models.BooleanField(default=True)
    dungeon = models.BooleanField(default=True)
    guild = models.BooleanField(default=True)

    objects = ProfileManager()

    def __str__(self):
        return f"{self.last_known_nickname}({self.uid})"

    @staticmethod
    def from_tag(tag, client, server, message):
        maybe_user_id = Profile.user_id_regex.match(tag)
        if maybe_user_id:
            user_id = int(maybe_user_id.group(1))
            profile, _ = Profile.objects.get_or_create(
                uid=user_id,
                defaults={
                    "last_known_nickname": client.get_user(user_id).name,
                    "server": server,
                    "channel": message.channel.id,
                },
            )
            return profile


class CoolDown(models.Model):
    class Meta:
        unique_together = ("profile", "type")

    time_regex = re.compile(
        r"(?P<days>\d{1}d)?\s*(?P<hours>\d{1,2}h)?\s*(?P<minutes>\d{1,2}m)?\s*(?P<seconds>\d{1,2}s)"
    )
    on_cooldown_regex = re.compile(r":clock4: ~-~ \*\*`(?P<field_name>[^`]*)`\*\*")
    off_cooldown_regex = re.compile(r":white_check_mark: ~-~ \*\*`(?P<field_name>[^`]*)`\*\*")

    COOLDOWN_TYPE_CHOICES = (
        ("daily", "Time for your daily! :sun_with_face:"),
        ("weekly", "Looks like it's that time of the week... :newspaper:"),
        ("lootbox", "Lootbox! :moneybag:"),
        ("vote", "You can vote again. :ballot_box:"),
        ("hunt", "is on the hunt! :crossed_swords:"),
        ("adventure", "Let's go on an adventure! :woman_running:"),
        ("quest", "The townspeople need our help! "),
        ("training", "want to get buff? :man_lifting_weights:"),
        ("duel", "It's time to d-d-d-d-duel! :crossed_swords:"),
        ("work", "Get back to work. :pick:"),
        ("horse", "Pie-O-My! :horse_racing:"),
        ("arena", "Heeyyyy lets go hurt each other. :circus_tent:"),
        ("dungeon", "can you reach the next area? :exclamation:"),
        ("guild", "Hey, those people are different! Get 'em! :shield:"),
    )
    COOLDOWN_TEXT_MAP = {c[0]: c[1] for c in COOLDOWN_TYPE_CHOICES}
    COOLDOWN_MAP = {
        "daily": datetime.timedelta(hours=24),
        "weekly": datetime.timedelta(days=7),
        "lootbox": datetime.timedelta(hours=3),
        "vote": datetime.timedelta(hours=12),
        "hunt": datetime.timedelta(seconds=60),
        "adventure": datetime.timedelta(minutes=60),
        "quest": datetime.timedelta(hours=6),
        "training": datetime.timedelta(minutes=15),
        "duel": datetime.timedelta(hours=2),
        "work": datetime.timedelta(minutes=5),
        "horse": datetime.timedelta(hours=24),
        "arena": datetime.timedelta(hours=24),
        "dungeon": datetime.timedelta(hours=12),
        "guild": datetime.timedelta(hours=2),
    }
    COOLDOWN_RESPONSE_CUE_MAP = {
        "have claimed your daily": "daily",
        "have claimed your weekly": "weekly",
        "have already bought a lootbox": "lootbox",
        # "": "vote", response does not give a cue
        "have already looked around": "hunt",
        "have already been in an adventure": "adventure",
        "have already claimed a quest": "quest",
        "have trained already": "training",
        "have been in a duel recently": "duel",
        "have already got some resources": "work",
        "have used this command recently": "horse",
        "have started an arena recently": "arena",
        "have been in a fight with a boss": "dungeon",
        "guild has already raided": "guild",
    }
    COMMAND_RESOLUTION_MAP = {
        "daily": lambda x: "daily",
        "weekly": lambda x: "weekly",
        "buy": lambda x: "lootbox" if "lootbox" in x else None,
        "vote": lambda x: "vote",
        "hunt": lambda x: "hunt",
        "adv": lambda x: "adventure",
        "adventure": lambda x: "adventure",
        "quest": lambda x: "quest",
        "epic": lambda x: "quest" if "quest" in x else None,
        "tr": lambda x: "training",
        "training": lambda x: "training",
        "ultraining": lambda x: "training",
        "duel": lambda x: "duel",
        "mine": lambda x: "work",
        "pickaxe": lambda x: "work",
        "drill": lambda x: "work",
        "dynamite": lambda x: "work",
        "pickup": lambda x: "work",
        "ladder": lambda x: "work",
        "tractor": lambda x: "work",
        "greenhouse": lambda x: "work",
        "chop": lambda x: "work",
        "axe": lambda x: "work",
        "bowsaw": lambda x: "work",
        "chainsaw": lambda x: "work",
        "fish": lambda x: "work",
        "net": lambda x: "work",
        "boat": lambda x: "work",
        "bigboat": lambda x: "work",
        "horse": lambda x: "horse" if any([o == x for o in ["training", "breeding", "race"]]) else None,
        "arena": lambda x: "arena",
        "big": lambda x: "arena" if "arena" in x else None,
        "dungeon": lambda x: "dungeon",
        "miniboss": lambda x: "dungeon",
        "not so mini boss": lambda x: "dungeon" if "join" in x else None,
        "guild": lambda x: "guild" if "raid" in x else None,
    }

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    type = models.CharField(choices=COOLDOWN_TYPE_CHOICES, max_length=10)
    after = models.DateTimeField()

    def __str__(self):
        return f"{self.profile} can {self.type} after {self.after}"

    @staticmethod
    def cd_from_command(cmd):
        resolved = None
        tokens = tokenize(cmd)
        if not tokens:
            return None, None
        # zero argument commands will just return whether or not the command matched
        if len(tokens) == 1:
            resolved = CoolDown.COMMAND_RESOLUTION_MAP.get(tokens[0], lambda x: None)("")
        else:
            cmd, *args = tokens
            # mutli-arguments must be resolved in the basis of other args
            resolved = CoolDown.COMMAND_RESOLUTION_MAP.get(cmd, lambda x: None)(" ".join(args))
        if not resolved:
            return None, None
        return resolved, datetime.datetime.now(tz=datetime.timezone.utc) + CoolDown.COOLDOWN_MAP[resolved]

    @staticmethod
    def from_cd(profile, fields):
        start = datetime.datetime.now(tz=datetime.timezone.utc)
        cooldown_updates, cooldown_evictions = [], []
        cd_types = set(c[0] for c in CoolDown.COOLDOWN_TYPE_CHOICES)
        for field in fields:
            fields_on_cooldown = CoolDown.on_cooldown_regex.findall(field)
            fields_off_cooldown = CoolDown.off_cooldown_regex.findall(field)
            if fields_on_cooldown:
                time_matches = CoolDown.time_regex.findall(field)
                for i, field_on_cooldown in enumerate(fields_on_cooldown):
                    time_delta_params = {
                        key: int(time_matches[i][j][:-1]) if time_matches[i][j] else 0
                        for j, key in enumerate(["days", "hours", "minutes", "seconds"])
                    }
                    after = start + datetime.timedelta(**time_delta_params)
                    for cd_type in cd_types:
                        if cd_type in field_on_cooldown.lower():
                            cooldown_updates.append(CoolDown(profile=profile, type=cd_type, after=after))
                            cd_types.remove(cd_type)
                            break
                    # special case
                    if "mine" in field_on_cooldown.lower():
                        cooldown_updates.append(CoolDown(profile=profile, type="work", after=after))
            if fields_off_cooldown:
                for field_off_cooldown in fields_off_cooldown:
                    for cd_type in cd_types:
                        if cd_type in field_off_cooldown.lower():
                            cooldown_evictions.append({"profile": profile, "type": cd_type})
                            cd_types.remove(cd_type)
                            break
                    if "mine" in field_off_cooldown.lower():
                        cooldown_evictions.append({"profile": profile, "type": "mine"})
        return cooldown_updates, cooldown_evictions

    @staticmethod
    def from_cooldown_reponse(profile, title, _type):
        start = datetime.datetime.now(tz=datetime.timezone.utc)
        time_match = CoolDown.time_regex.search(title)
        if time_match:
            time_match = time_match.groupdict()
            time_delta_params = {
                key: int(time_match[key][:-1]) if time_match[key] else 0
                for key in ["days", "hours", "minutes", "seconds"]
            }
            return [CoolDown(profile=profile, type=_type, after=start + datetime.timedelta(**time_delta_params))]
        return []


class Gamble(models.Model):
    GAME_TYPE_CHOICES = (
        ("bj", "Blackjack"),
        ("cf", "Coinflip"),
        ("slots", "Slots"),
        ("dice", "Dice"),
    )
    OUTCOME_CHOICES = (
        # past tense is more convenient
        ("won", "Win"),
        ("lost", "Loss"),
        ("tied", "Tie"),
    )
    GAME_CUE_MAP = {
        "blackjack": "bj",
        "dice": "dice",
        "slots": "slots",
        "coinflip": "cf",
    }
    profile = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True)
    game = models.CharField(choices=GAME_TYPE_CHOICES, max_length=5)
    outcome = models.CharField(choices=OUTCOME_CHOICES, max_length=4)
    net = models.IntegerField()
    created = models.DateTimeField(auto_now=True)

    objects = GamblingStatsManager()

    def __str__(self):
        name = self.profile.last_known_nickname if self.profile else "Anonymous"
        return f"{name} {self.outcome} {abs(self.net)} playing {self.game}"

    @staticmethod
    def from_results_screen(profile, embed):
        game_regex = re.compile(r"(blackjack|dice|slots|coinflip)")
        game_match = game_regex.search(embed.author.name)
        if not game_match:
            return None
        game = game_match.group(1)
        "it's a tie lmao"
        outcome_regex = re.compile(r"(?P<outcome>won|lost) (\*{2})?(?P<amount>[0-9,]+)(\*{2})? coins")
        gamble = None
        if game in {"blackjack", "dice", "coinflip"}:
            for field in embed.fields:
                name_match, value_match = outcome_regex.search(field.name), outcome_regex.search(field.value)
                if name_match:
                    outcome, _, amount, _ = name_match.groups()
                    amount = amount.replace(",", "")
                    net = -int(amount) if outcome == "lost" else int(amount)
                    gamble = Gamble(profile=profile, game=Gamble.GAME_CUE_MAP[game], outcome=outcome, net=net)
                elif value_match:
                    outcome, _, amount, _ = value_match.groups()
                    amount = amount.replace(",", "")
                    net = -int(amount) if outcome == "lost" else int(amount)
                    gamble = Gamble(profile=profile, game=Gamble.GAME_CUE_MAP[game], outcome=outcome, net=net)
                elif "it's a tie lmao" in field.name:
                    gamble = Gamble(profile=profile, game=Gamble.GAME_CUE_MAP[game], outcome="tied", net=0)
        elif game == "slots":
            outcome_match = outcome_regex.search(embed.description)
            if outcome_match:
                outcome, _, amount, _ = outcome_match.groups()
                amount = amount.replace(",", "")
                net = -int(amount) if outcome == "lost" else int(amount)
                gamble = Gamble(profile=profile, game=Gamble.GAME_CUE_MAP[game], outcome=outcome, net=net)
        return gamble

    @sync_to_async
    def asave(self, *args, **kwargs):
        return super().save(*args, **kwargs)


class Hunt(UpdateAble, models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, related_name="hunts")
    target = models.CharField(max_length=50, db_index=True, null=True, blank=True)
    money = models.PositiveBigIntegerField(null=True, blank=True)
    xp = models.PositiveBigIntegerField(null=True, blank=True)
    loot = models.CharField(max_length=50, db_index=True, null=True, blank=True)

    objects = HuntManager()

    def __str__(self):
        name = self.profile.last_known_nickname if self.profile else "Anonymous"
        return f"{name} killed a {self.target}"

    @staticmethod
    def save_hunt_result(message):
        "got a wolf skin"
        "got a rare lootbox"
        "got an <:unicornhorn:545329267425149112> unicorn horn"
        target_regex = re.compile(r"\*\*(?P<name>[^\*]+)\*\* found and killed a [^\*]+\*\*(?P<target>[^\*]+)\*\*")
        earnings_regex = re.compile(r"Earned ([0-9,]+) coins and ([0-9,]+) XP")
        loot_regex = re.compile(r"got an? (\s*<:[^:]+:\d+>\s*)?(?P<loot>[\w ]+)(\s*<:[^:]+:\d+>\s*)?")
        target_match = target_regex.search(message.content)
        earnings_match = earnings_regex.search(message.content)
        loot_match = loot_regex.search(message.content)
        if target_match and earnings_match:
            name, target = target_match.group(1), target_match.group(2)
            money, xp = earnings_match.group(1).replace(",", ""), earnings_match.group(2).replace(",", "")
            loot = ""
            if loot_match:
                loot = loot_match.group(2).strip()
            return name, target, money, xp, loot
        else:
            return
