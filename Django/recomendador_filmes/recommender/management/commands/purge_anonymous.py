from django.core.management.base import BaseCommand

from recommender.maintenance import purge_anonymous


class Command(BaseCommand):
    help = 'Apaga sessões expiradas e o histórico de gosto anônimo que ficou sem sessão.'

    def handle(self, *args, **options):
        resultado = purge_anonymous()
        self.stdout.write(self.style.SUCCESS(
            f"{resultado['sessions']} sessões expiradas, {resultado['owners']} perfis anônimos órfãos: "
            f"{resultado['interactions']} interações e {resultado['events']} eventos apagados."
        ))
