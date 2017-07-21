from flask import url_for

from decksite.data import archetype as archs
from decksite.view import View

# pylint: disable=no-self-use
class Archetype(View):
    def __init__(self, archetype, archetypes, matchups):
        self.archetype = next(a for a in archetypes if a.id == archetype.id)
        self.archetype.decks = archetype.decks
        # Load the deck information from archetype into skinny archetype loaded by load_archetypes_deckless_for with tree information.
        self.archetypes = archetypes
        self.decks = self.archetype.decks
        self.roots = [a for a in self.archetypes if a.is_root]
        matchup_archetypes = archs.load_archetypes_deckless()
        matchups_by_id = {m.id: m for m in matchups}
        for m in matchup_archetypes:
            n = matchups_by_id.get(m.id)
            if n is not None:
                m.update(n)
            self.prepare_archetype(m, matchup_archetypes)
        # Storing this in matchups_container like this lets us include two different archetype trees on the same page without collision.
        self.matchups_container = [{
            'hide_num_decks': True,
            'roots': [m for m in matchup_archetypes if m.is_root],
        }]

    def __getattr__(self, attr):
        return getattr(self.archetype, attr)

    def subtitle(self):
        return self.archetype.name
