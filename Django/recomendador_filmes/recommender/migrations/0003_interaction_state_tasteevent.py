"""Troca o sinal binário (1 / -1) por um estado único por título e cria o log de eventos."""
import django.db.models.deletion
from django.db import migrations, models

STATES = [
    ('favorite', 'Favorito'),
    ('like', 'Curti'),
    ('dislike', 'Não curti'),
    ('seen', 'Já vi'),
    ('watchlist', 'Quero assistir'),
]


def sinal_para_estado(apps, schema_editor):
    Interaction = apps.get_model('recommender', 'Interaction')
    Interaction.objects.filter(signal=1).update(state='like')
    Interaction.objects.filter(signal=-1).update(state='dislike')


def estado_para_sinal(apps, schema_editor):
    Interaction = apps.get_model('recommender', 'Interaction')
    Interaction.objects.filter(state__in=['favorite', 'like']).update(signal=1)
    Interaction.objects.filter(state='dislike').update(signal=-1)
    # "Já vi" e "Quero assistir" não existem no formato antigo.
    Interaction.objects.filter(state__in=['seen', 'watchlist']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
        ('recommender', '0002_userpreferences'),
    ]

    operations = [
        migrations.AddField(
            model_name='interaction',
            name='state',
            field=models.CharField(choices=STATES, max_length=9, null=True, verbose_name='estado'),
        ),
        migrations.AlterField(
            model_name='interaction',
            name='signal',
            field=models.SmallIntegerField(choices=[(1, 'Curti'), (-1, 'Não curti')], null=True, verbose_name='sinal'),
        ),
        migrations.RunPython(sinal_para_estado, estado_para_sinal),
        migrations.RemoveField(model_name='interaction', name='signal'),
        migrations.AlterField(
            model_name='interaction',
            name='state',
            field=models.CharField(choices=STATES, max_length=9, verbose_name='estado'),
        ),
        migrations.CreateModel(
            name='TasteEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner', models.CharField(db_index=True, max_length=64, verbose_name='dono')),
                ('from_state', models.CharField(blank=True, choices=STATES, max_length=9, verbose_name='de')),
                ('to_state', models.CharField(blank=True, choices=STATES, max_length=9, verbose_name='para')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('title', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='taste_events', to='catalog.title',
                )),
            ],
            options={
                'verbose_name': 'evento de gosto',
                'verbose_name_plural': 'eventos de gosto',
                'ordering': ['created_at', 'id'],
            },
        ),
    ]
