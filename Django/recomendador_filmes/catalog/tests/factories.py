# catalog/tests/factories.py
"""Catálogo pequeno e controlado, usado pelos testes de catálogo, motor e API."""
from catalog.importers import NormalizedTitle

SPACE = 'A crew of astronauts travels through a wormhole aboard a spaceship to find a new home planet.'
ROMANCE = 'Two strangers fall in love in Paris during a rainy summer and must choose between career and romance.'


def titulo(external_id, title, kind='movie', **extra):
    dados = {
        'kind': kind,
        'source': 'mal' if kind == 'anime' else 'tmdb',
        'external_id': str(external_id),
        'title': title,
        'year': 2010,
        'vote_average': 7.5,
        'vote_count': 5000,
        'popularity': 50.0,
    }
    dados.update(extra)
    return NormalizedTitle(**dados)


def sample_catalog():
    return [
        titulo(1, 'Space Odyssey', overview=SPACE, genres=['Science Fiction', 'Adventure'],
               director='Ridley Scott', keywords='space wormhole', year=2014, popularity=90),
        titulo(2, 'Space Return', overview=SPACE + ' The sequel.', genres=['Science Fiction', 'Adventure'],
               director='Ridley Scott', keywords='space sequel', year=2016, popularity=80),
        titulo(3, 'Orbit', overview='An astronaut stranded in orbit fights to survive aboard a damaged spaceship.',
               genres=['Science Fiction', 'Thriller'], keywords='space survival', year=2013, popularity=85),
        titulo(4, 'Paris Rain', overview=ROMANCE, genres=['Romance', 'Comedy'], keywords='love paris', popularity=70),
        titulo(5, 'Summer Letters', overview=ROMANCE + ' Letters connect them.', genres=['Romance', 'Drama'],
               keywords='love letters', popularity=60),
        titulo(6, 'Garage Spaceship', overview='Two kids build a spaceship in a garage and fly it to the moon.',
               genres=['Science Fiction', 'Adventure'], keywords='space garage', vote_count=3, vote_average=9.5,
               popularity=1),
        titulo(7, 'Star Pilots', kind='anime', overview='Teenage pilots defend a space colony with giant robots in orbit.',
               genres=['Animation', 'Science Fiction', 'Action'], director='Sunrise', keywords='Manga space',
               vote_count=400000, popularity=900000),
        # A mesma obra de 'Space Odyssey', vinda de outra fonte.
        titulo(8, 'Space Odyssey', kind='anime', overview=SPACE, genres=['Animation', 'Science Fiction'],
               year=2014, vote_count=100000, popularity=500000),
        titulo(9, 'Office Days', kind='series', overview='Coworkers at a paper company deal with an awkward boss.',
               genres=['Comedy'], director='Greg Daniels', vote_count=4000, popularity=200),
    ]
