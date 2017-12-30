from decksite.view import View

# pylint: disable=no-self-use
class RotationChanges(View):
    def __init__(self, cards_in, cards_out):
        self.sections = []
        self.cards = cards_in + cards_out
        entries_in = [{'name': c.name, 'card': c} for c in cards_in]
        entries_out = [{'name': c.name, 'card': c} for c in cards_out]
        self.sections.append({'name': 'New this season', 'entries': entries_in, 'num_entries': len(entries_in)})
        self.sections.append({'name': 'Rotated out', 'entries': entries_out, 'num_entries': len(entries_out)})

    def subtitle(self):
        return 'Rotation Changes'
