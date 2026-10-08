# Mémoire de séance du lecteur : ce qu'est une page LUE.
#
# Avant, « pages lues » était la page la plus avancée envoyée par le client, et
# le bonus d'attention comptait toute page dominante une fraction de seconde.
# Une page est lue quand le temps passé dessus dans la séance (pauses exclues)
# atteint PAGE_READ_MIN_DWELL_S — et le sas d'entrée n'est pas une lecture.
from config.settings import PAGE_READ_MIN_DWELL_S
from services.session_memory import SessionMemory


def _reading(at: float = 0.0, page: int = 1) -> SessionMemory:
    memory = SessionMemory()
    memory.on_page_view(page, now=at)
    memory.start_reading(now=at)
    return memory


def test_scrolling_through_pages_reads_none_of_them():
    memory = _reading()
    for n in range(2, 21):
        memory.on_page_view(n, now=0.1 * (n - 1))
    assert memory.pages_read(now=2.0) == set()
    # Elles ont toutes été vues : la visite reste un signal à part.
    assert memory.pages_seen() == set(range(1, 21))


def test_a_page_is_read_once_its_time_reaches_the_threshold():
    memory = _reading(page=7)
    assert memory.pages_read(now=PAGE_READ_MIN_DWELL_S - 0.5) == set()
    # La page à l'écran compte en direct, sans qu'il faille la quitter.
    assert memory.pages_read(now=PAGE_READ_MIN_DWELL_S + 1.0) == {7}


def test_time_adds_up_across_visits():
    memory = _reading(page=3)
    half = PAGE_READ_MIN_DWELL_S * 0.6
    memory.on_page_view(4, now=half)
    memory.on_page_view(3, now=half + 0.1)
    assert memory.pages_read(now=half + 0.1 + half) == {3}


def test_a_pause_is_not_reading_time():
    memory = _reading(page=2)
    # Pause de 100 s ouverte à t=1 : pendant, rien ne s'ajoute (une séance
    # terminée depuis l'écran de pause) ; à la reprise, l'horloge de la page recule.
    memory.pause(now=1.0)
    assert memory.pages_read(now=100.0) == set()
    memory.skip(100.0)
    assert memory.pages_read(now=101.0 + PAGE_READ_MIN_DWELL_S - 2.0) == set()
    assert memory.pages_read(now=101.0 + PAGE_READ_MIN_DWELL_S) == {2}


def test_the_live_count_is_read_from_the_reader_still_open():
    """`/end` lit le compte exact de la séance en cours, sans attendre un tick."""
    from services import session_memory

    memory = _reading(page=4, at=0.0)
    other = SessionMemory()
    session_memory.track(41, memory)
    try:
        # Entrée à t=0 de l'horloge monotone : la page est lue depuis longtemps.
        assert session_memory.live_pages_read(41) == 1
        session_memory.untrack(41, other)  # un autre socket ne la retire pas
        assert session_memory.live_pages_read(41) == 1
    finally:
        session_memory.untrack(41, memory)
    assert session_memory.live_pages_read(41) is None


def test_the_entry_sas_is_not_a_reading_of_page_one():
    memory = SessionMemory()
    memory.on_page_view(1, now=0.0)  # socket ouvert : le sas commence
    assert memory.pages_read(now=60.0) == set()  # une minute de sas, rien de lu
    memory.start_reading(now=60.0)
    assert memory.dwell_by_page == {1: 0.0} and memory.visits_by_page == {1: 1}
    assert memory.pages_read(now=62.0) == set()
    assert memory.pages_read(now=60.0 + PAGE_READ_MIN_DWELL_S) == {1}


def test_start_reading_only_counts_once():
    memory = _reading()
    memory.on_page_view(2, now=1.0)
    memory.start_reading(now=PAGE_READ_MIN_DWELL_S + 10.0)  # un second envoi ne remet rien à zéro
    assert memory.pages_read(now=PAGE_READ_MIN_DWELL_S + 10.0) == {2}
