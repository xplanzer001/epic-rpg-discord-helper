# Generated by Django 3.1.3 on 2020-11-26 03:34

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('epic', '0007_group_guild_cd'),
    ]

    operations = [
        migrations.CreateModel(
            name='Gamble',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('game', models.CharField(choices=[('bj', 'Blackjack'), ('cf', 'Coinflip'), ('slots', 'Slots'), ('dice', 'Dice')], max_length=5)),
                ('outcome', models.CharField(choices=[('won', 'Win'), ('lost', 'Loss'), ('tied', 'Tie')], max_length=4)),
                ('net', models.IntegerField()),
                ('profile', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='epic.profile')),
            ],
        ),
    ]
