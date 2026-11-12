"""
Recria as tabelas de usuários, permissões e admin para adotar `accounts.User`.

Trocar AUTH_USER_MODEL num banco já migrado não tem migração possível: o histórico do
`admin` (e de quem aponta para o usuário) foi aplicado contra `auth.User`, e o `migrate`
recusa seguir com InconsistentMigrationHistory. Este comando apaga essas tabelas e as
linhas correspondentes em django_migrations e migra de novo só esses apps.

Catálogo, interações e sessões ficam intactos: os visitantes anônimos mantêm os seus perfis
(e quem estava logado com o usuário antigo é deslogado sozinho). Usuários e o registro de
ações do admin são perdidos: crie o superusuário de novo depois.

Só os apps de autenticação são migrados aqui; rode `migrate` depois para o resto, quando o
código novo estiver no ar (algumas migrações mudam tabelas que o código antigo usa).
"""
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection

APPS = ('auth', 'accounts', 'admin', 'axes')  # na ordem de dependência
TABLE_PREFIXES = ('auth_', 'django_admin_log', 'accounts_', 'axes_')
# Tabelas de outros apps que apontam para o usuário (recriadas pelas próprias migrações).
DEPENDENT_TABLES = {'recommender_userpreferences': ('recommender', '0002_userpreferences')}


class Command(BaseCommand):
    help = 'Recria as tabelas de autenticação para adotar accounts.User (perde os usuários; mantém as sessões).'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Confirma a operação sem perguntar.')
        parser.add_argument(
            '--force', action='store_true',
            help='Segue mesmo que existam usuários comuns (não superusuários), que serão perdidos.',
        )

    def handle(self, *args, yes, force, **options):
        tabelas = connection.introspection.table_names()
        alvo = [t for t in tabelas if t.startswith(TABLE_PREFIXES)]
        alvo += [t for t in DEPENDENT_TABLES if t in tabelas]
        if not alvo:
            self.stdout.write('Nenhuma tabela de autenticação encontrada. Migrando os apps de autenticação.')
            self._migrate_auth()
            return

        usuarios = self._usuarios(tabelas)
        comuns = [u for u in usuarios if not u[1]]
        self.stdout.write(f'Banco: {connection.vendor} ({connection.settings_dict.get("NAME")})')
        self.stdout.write(f'Tabelas a recriar: {", ".join(sorted(alvo))}')
        self.stdout.write(
            f'Usuários que serão apagados: {len(usuarios)} '
            f'({len(usuarios) - len(comuns)} superusuários, {len(comuns)} comuns)'
        )
        if comuns and not force:
            raise CommandError('Há usuários comuns no banco. Use --force se quiser apagá-los mesmo assim.')
        if not yes and input('Digite "recriar" para continuar: ').strip() != 'recriar':
            raise CommandError('Operação cancelada.')

        with connection.constraint_checks_disabled(), connection.cursor() as cursor:
            for tabela in alvo:
                cascata = ' CASCADE' if connection.vendor == 'postgresql' else ''
                cursor.execute(f'DROP TABLE IF EXISTS {connection.ops.quote_name(tabela)}{cascata}')
            cursor.execute(
                f'DELETE FROM django_migrations WHERE app IN ({", ".join(["%s"] * len(APPS))})', APPS,
            )
            for tabela, (app, migracao) in DEPENDENT_TABLES.items():
                if tabela in alvo:
                    cursor.execute('DELETE FROM django_migrations WHERE app = %s AND name = %s', [app, migracao])

        self.stdout.write(self.style.SUCCESS('Tabelas apagadas. Migrando os apps de autenticação.'))
        self._migrate_auth()
        self.stdout.write(self.style.SUCCESS(
            'Pronto. Crie o superusuário (python manage.py createsuperuser) e rode `migrate` '
            'para as demais migrações quando o código novo estiver no ar.'
        ))

    def _migrate_auth(self):
        for app in APPS:
            call_command('migrate', app, interactive=False, verbosity=0)
            self.stdout.write(f'  {app}: ok')

    def _usuarios(self, tabelas):
        for tabela in ('accounts_user', 'auth_user'):
            if tabela in tabelas:
                with connection.cursor() as cursor:
                    cursor.execute(f'SELECT id, is_superuser FROM {connection.ops.quote_name(tabela)}')
                    return cursor.fetchall()
        return []
