# Generated by Django 3.1.3 on 2020-11-26 08:50

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('epic', '0009_gamble_created'),
    ]

    operations = [
        migrations.CreateModel(
            name='Hunt',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('target', models.CharField(blank=True, db_index=True, max_length=50, null=True)),
                ('money', models.PositiveBigIntegerField(blank=True, null=True)),
                ('xp', models.PositiveBigIntegerField(blank=True, null=True)),
                ('loot', models.CharField(blank=True, db_index=True, max_length=50, null=True)),
                ('profile', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='hunts', to='epic.profile')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
