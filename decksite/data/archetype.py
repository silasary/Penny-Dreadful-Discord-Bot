import sys
from typing import Dict, List

import titlecase
from anytree import NodeMixin

from decksite.data import deck, query
from decksite.database import db
from magic import rotation
from shared.container import Container
from shared.database import sqlescape
from shared.pd_exception import DoesNotExistException, TooManyItemsException


class Archetype(Container, NodeMixin):
    pass

BASE_ARCHETYPES: Dict[Archetype, Archetype] = {}

def load_archetype(archetype, season_id=None):
    try:
        archetype_id = int(archetype)
    except ValueError:
        name = titlecase.titlecase(archetype)
        name_without_dashes = name.replace('-', ' ')
        archetype_id = db().value('SELECT id FROM archetype WHERE name IN (%s, %s)', [name, name_without_dashes])
        if not archetype_id:
            raise DoesNotExistException('Did not find archetype with name of `{name}`'.format(name=name))
    archetypes = load_archetypes(where='d.archetype_id IN (SELECT descendant FROM archetype_closure WHERE ancestor = {archetype_id})'.format(archetype_id=sqlescape(archetype_id)), merge=True, season_id=season_id)
    if len(archetypes) > 1:
        raise TooManyItemsException('Found {n} archetypes when expecting 1 at most'.format(n=len(archetypes)))
    archetype = archetypes[0] if len(archetypes) == 1 else Archetype()
    # Because load_archetypes loads the root archetype and all below merged the id and name might not be those of the root archetype. Overwrite.
    archetype.id = int(archetype_id)
    archetype.name = db().value('SELECT name FROM archetype WHERE id = %s', [archetype_id])
    if len(archetypes) == 0:
        archetype.decks = []
    return archetype

def load_archetypes(where: str = '1 = 1', merge: bool = False, season_id: int = None) -> List[Archetype]:
    decks = deck.load_decks(where, season_id=season_id)
    archetypes: Dict[str, Archetype] = {}
    for d in decks:
        if d.archetype_id is None:
            continue
        key = 'merge' if merge else d.archetype_id
        archetype = archetypes.get(key, Archetype())
        archetype.id = d.archetype_id
        archetype.name = d.archetype_name
        archetype.decks = archetype.get('decks', []) + [d]
        archetype.all_wins = archetype.get('all_wins', 0) + (d.get('all_wins') or 0)
        archetype.all_losses = archetype.get('all_losses', 0) + (d.get('all_losses') or 0)
        archetype.all_draws = archetype.get('all_draws', 0) + (d.get('all_draws') or 0)
        if d.get('finish') == 1:
            archetype.all_tournament_wins = archetype.get('all_tournament_wins', 0) + 1
        if (d.get('finish') or sys.maxsize) <= 8:
            archetype.all_top8s = archetype.get('all_top8s', 0) + 1
            archetype.all_perfect_runs = archetype.get('all_perfect_runs', 0) + 1
        if d.active_date >= rotation.last_rotation():
            archetype.season_wins = archetype.get('season_wins', 0) + (d.get('season_wins') or 0)
            archetype.season_losses = archetype.get('season_losses', 0) + (d.get('season_losses') or 0)
            archetype.season_draws = archetype.get('season_draws', 0) + (d.get('season_draws') or 0)
            if d.get('finish') == 1:
                archetype.season_tournament_wins = archetype.get('season_tournament_wins', 0) + 1
            if (d.get('finish') or sys.maxsize) <= 8:
                archetype.season_top8s = archetype.get('season_top8s', 0) + 1
            if d.source_name == 'League' and d.wins >= 5 and d.losses == 0:
                archetype.season_perfect_runs = archetype.get('season_all_perfect_runs', 0) + 1
        archetypes[key] = archetype
    archetype_list = list(archetypes.values())
    return archetype_list

def load_archetypes_deckless(where: str = '1 = 1',
                             order_by: str = '`all_num_decks` DESC, `all_wins` DESC, name',
                             season_id: int = None) -> List[Archetype]:
    sql = """
        SELECT
            a.id,
            a.name,
            aca.ancestor AS parent_id,
            {all_select}
        FROM
            archetype AS a
        LEFT JOIN
            archetype_closure AS aca ON a.id = aca.descendant AND aca.depth = 1
        LEFT JOIN
            archetype_closure AS acd ON a.id = acd.ancestor
        LEFT JOIN
            deck AS d ON acd.descendant = d.archetype_id
        {season_join}
        {nwdl_join}
        WHERE ({where}) AND ({season_query})
        GROUP BY
            a.id,
            aca.ancestor -- aca.ancestor will be unique per a.id because of integrity constraints enforced elsewhere (each archetype has one ancestor) but we let the database know here.
        ORDER BY
            {order_by}
    """.format(all_select=deck.nwdl_all_select(), season_join=query.season_join(), nwdl_join=deck.nwdl_join(), where=where, season_query=query.season_query(season_id), order_by=order_by)
    archetypes = [Archetype(a) for a in db().select(sql)]
    archetypes_by_id = {a.id: a for a in archetypes}
    for a in archetypes:
        a.decks = []
        a.parent = archetypes_by_id.get(a.parent_id, None)
    return archetypes

def load_archetypes_deckless_for(archetype_id: int, season_id: int = None) -> List[Archetype]:
    archetypes = load_archetypes_deckless(season_id=season_id)
    for a in archetypes:
        if int(a.id) == int(archetype_id):
            return list(a.ancestors) + [a] + list(a.descendants)
    return list()

def add(name: str, parent: int) -> None:
    archetype_id = db().insert('INSERT INTO archetype (name) VALUES (%s)', [name])
    ancestors = db().select('SELECT ancestor, depth FROM archetype_closure WHERE descendant = %s', [parent])
    sql = 'INSERT INTO archetype_closure (ancestor, descendant, depth) VALUES '
    for a in ancestors:
        sql += '({ancestor}, {descendant}, {depth}), '.format(ancestor=sqlescape(a['ancestor']), descendant=archetype_id, depth=int(a['depth']) + 1)
    sql += '({ancestor}, {descendant}, {depth})'.format(ancestor=archetype_id, descendant=archetype_id, depth=0)
    db().execute(sql)

def assign(deck_id: int, archetype_id: int, reviewed: bool = True) -> None:
    db().execute('UPDATE deck SET reviewed = %s, archetype_id = %s WHERE id = %s', [reviewed, archetype_id, deck_id])

def load_all_matchups(where='TRUE', season_id=None):
    sql = """
        SELECT
            a.id AS archetype_id,
            a.name AS archetype_name,
            oa.id,
            oa.name,
            SUM(CASE WHEN dm.games > IFNULL(odm.games, 0) THEN 1 ELSE 0 END) AS all_wins, -- IFNULL so we still count byes as wins.
            SUM(CASE WHEN dm.games < odm.games THEN 1 ELSE 0 END) AS all_losses,
            SUM(CASE WHEN dm.games = odm.games THEN 1 ELSE 0 END) AS all_draws,
            IFNULL(ROUND((SUM(CASE WHEN dm.games > odm.games THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN dm.games <> IFNULL(odm.games, 0) THEN 1 ELSE 0 END), 0)) * 100, 1), '') AS all_win_percent
        FROM
            archetype AS a
        INNER JOIN
            deck AS d ON d.archetype_id IN (SELECT descendant FROM archetype_closure WHERE ancestor = a.id)
        INNER JOIN
            deck_match AS dm ON d.id = dm.deck_id
        INNER JOIN
            deck_match AS odm ON dm.match_id = odm.match_id AND odm.deck_id <> d.id
        INNER JOIN
            deck AS od ON od.id = odm.deck_id
        INNER JOIN
            archetype AS oa ON od.archetype_id IN (SELECT descendant FROM archetype_closure WHERE ancestor = oa.id)
        {season_join}
        WHERE
            ({where}) AND ({season_query})
        GROUP BY
            a.id,
            oa.id
        ORDER BY
            `all_wins` DESC,
            oa.name
    """.format(season_join=query.season_join(), where=where, season_query=query.season_query(season_id))
    return [Container(m) for m in db().select(sql)]

def load_matchups(archetype_id, season_id=None):
    where = 'a.id = {archetype_id}'.format(archetype_id=archetype_id)
    return load_all_matchups(where, season_id)

def move(archetype_id: int, parent_id: int) -> None:
    db().begin()
    remove_sql = """
        DELETE a
        FROM archetype_closure AS a
        INNER JOIN archetype_closure AS d
            ON a.descendant = d.descendant
        LEFT JOIN archetype_closure AS x
            ON x.ancestor = d.ancestor AND x.descendant = a.ancestor
        WHERE d.ancestor = %s AND x.ancestor IS NULL
    """
    db().execute(remove_sql, [archetype_id])
    add_sql = """
        INSERT INTO archetype_closure (ancestor, descendant, depth)
            SELECT supertree.ancestor, subtree.descendant, supertree.depth + subtree.depth + 1
            FROM archetype_closure AS supertree JOIN archetype_closure AS subtree
            WHERE subtree.ancestor = %s
            AND supertree.descendant = %s
    """
    db().execute(add_sql, [archetype_id, parent_id])
    db().commit()

def base_archetypes() -> List[Archetype]:
    return [a for a in base_archetype_by_id().values() if a.parent is None]

def base_archetype_by_id() -> Dict[Archetype, Archetype]:
    if len(BASE_ARCHETYPES) == 0:
        rebuild_archetypes()
    return BASE_ARCHETYPES

def rebuild_archetypes() -> None:
    archetypes_by_id = {a.id: a for a in load_archetypes_deckless()}
    for k, v in archetypes_by_id.items():
        p = v
        while p.parent is not None:
            p = p.parent
        BASE_ARCHETYPES[k] = p
