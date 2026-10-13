import os
import re
import json
import logging
import threading
from typing import List, Dict, Tuple, Set, Optional
import requests

from core.paths import get_cache_dir

logger = logging.getLogger("core.genre")


# Curated artist/band styles covering core genres, classical, world, regional, and Persian catalogs
CURATED_ARTIST_GENRES: Dict[str, List[str]] = {
    # Persian Traditional / Classical
    "mohammad-reza shajarian": ["Traditional Persian", "Classical Persian", "Sonati"],
    "homayoun shajarian": ["Traditional Persian", "Persian Pop", "Classical Persian"],
    "shahram nazeri": ["Traditional Persian", "Classical Persian", "Sufi Music"],
    "hossein alizadeh": ["Traditional Persian", "Classical Persian", "Instrumental"],
    "kayhan kalhor": ["Traditional Persian", "Classical Persian", "World"],
    "gholam-hossein banan": ["Traditional Persian", "Classical Persian"],
    "parviz meshkatian": ["Traditional Persian", "Classical Persian", "Santur"],
    "jalil shahnaz": ["Traditional Persian", "Classical Persian", "Tar"],
    "marzieh": ["Traditional Persian", "Classical Persian"],
    "delkash": ["Traditional Persian", "Classic Persian Pop"],
    "simin ghanem": ["Classic Persian Pop", "Persian Pop"],
    "pari zanganeh": ["Persian Folk", "Persian Traditional"],
    "sima bina": ["Persian Folk", "Traditional Persian"],
    
    # Persian Classic Pop / Golden Era
    "hayedeh": ["Classic Persian Pop", "Persian Pop", "Traditional Persian"],
    "mahasti": ["Classic Persian Pop", "Persian Pop"],
    "homeyra": ["Classic Persian Pop", "Persian Pop", "Traditional Persian"],
    "googoosh": ["Classic Persian Pop", "Persian Pop"],
    "ebi": ["Classic Persian Pop", "Persian Pop"],
    "dariush": ["Classic Persian Pop", "Persian Pop"],
    "moein": ["Classic Persian Pop", "Persian Pop", "Traditional Persian"],
    "sattar": ["Classic Persian Pop", "Persian Pop"],
    "siavash ghomayshi": ["Classic Persian Pop", "Persian Pop", "Persian Rock"],
    "habib": ["Classic Persian Pop", "Persian Rock", "Persian Folk"],
    "kourosh yaghmaei": ["Persian Psychedelic Rock", "Persian Rock", "Classic Persian Pop"],
    "faramarz aslani": ["Persian Pop", "Persian Acoustic", "Flamenco"],
    "viguen": ["Classic Persian Pop", "Persian Jazz", "Persian Pop"],
    "shamaizadeh": ["Classic Persian Pop", "Persian Pop"],
    "aref": ["Classic Persian Pop", "Persian Pop"],
    "bijan mortazavi": ["Persian Pop", "Classical Persian", "Instrumental Pop"],
    "shahram shabpareh": ["Classic Persian Pop", "Dance-Pop"],
    "leila forouhar": ["Classic Persian Pop", "Persian Pop"],
    "nooshafarin": ["Classic Persian Pop", "Persian Pop"],
    "shohreh": ["Classic Persian Pop", "Persian Pop"],
    "andi": ["Persian Pop", "Dance-Pop", "Armenian Pop"],
    "kouros": ["Persian Pop", "Dance-Pop"],

    # Modern Persian Pop & Rock
    "mohsen chavoshi": ["Persian Rock", "Persian Pop", "Alternative Rock"],
    "shadmehr aghili": ["Persian Pop", "Pop"],
    "sirvan khosravi": ["Persian Pop", "Electronic Pop"],
    "xaniar khosravi": ["Persian Pop", "Electronic Pop"],
    "reza sadeghi": ["Persian Pop", "Pop"],
    "ehsan khajehamiri": ["Persian Pop", "Pop"],
    "mohsen yeganeh": ["Persian Pop", "Pop"],
    "behnam bani": ["Persian Pop", "Pop"],
    "alireza talischi": ["Persian Pop", "Pop"],
    "ashvan": ["Persian Pop", "Pop"],
    "arash": ["Persian Pop", "Eurodance", "Dance-Pop"],
    "morteza pashaei": ["Persian Pop", "Pop"],
    "macan band": ["Persian Pop", "Pop"],
    "puzzle band": ["Persian Pop", "Electronic Pop"],
    "evan band": ["Persian Pop", "Pop"],
    "horoosh band": ["Persian Pop", "Pop"],
    "saman jalili": ["Persian Pop", "Pop"],
    "babak jahanbakhsh": ["Persian Pop", "Pop"],
    "farzad farzin": ["Persian Pop", "Electronic Pop"],
    "ali yasini": ["Persian Pop", "R&B"],
    "shervin hajipour": ["Persian Pop", "Indie Pop", "Acoustic Pop"],
    "mehdi yarrahi": ["Persian Pop", "Pop", "Arabic Pop"],
    "masoud sadeghloo": ["Persian Pop", "Pop"],
    "armin zarei": ["Persian Pop", "Persian Hip Hop"],
    "2afm": ["Persian Pop", "Persian Hip Hop"],

    # Persian Rap / Hip Hop
    "hichkas": ["Persian Hip Hop", "Rap Farsi", "Hip-Hop"],
    "yas": ["Persian Hip Hop", "Rap Farsi", "Conscious Hip-Hop"],
    "bahram": ["Persian Hip Hop", "Rap Farsi", "Underground Hip-Hop"],
    "shayea": ["Persian Hip Hop", "Rap Farsi", "Hip-Hop"],
    "reza pishro": ["Persian Hip Hop", "Rap Farsi", "Hardcore Hip-Hop"],
    "hoossein": ["Persian Hip Hop", "Rap Farsi", "Hip-Hop"],
    "hoossein eblis": ["Persian Hip Hop", "Rap Farsi", "Hip-Hop"],
    "fadaei": ["Persian Hip Hop", "Rap Farsi", "Political Hip-Hop"],
    "toomaj salehi": ["Persian Hip Hop", "Rap Farsi", "Protest Hip-Hop"],
    "erfan": ["Persian Hip Hop", "Rap Farsi"],
    "zedbazi": ["Persian Hip Hop", "Rap Farsi", "Trap"],
    "sohrab mj": ["Persian Hip Hop", "Rap Farsi"],
    "mehrad hidden": ["Persian Hip Hop", "Rap Farsi", "Alternative Rock"],
    "saman wilson": ["Persian Hip Hop", "Rap Farsi"],
    "sijal": ["Persian Hip Hop", "Rap Farsi"],
    "alireza jj": ["Persian Hip Hop", "Rap Farsi"],
    "khalse": ["Persian Hip Hop", "Rap Farsi", "Trap"],
    "leito": ["Persian Hip Hop", "Rap Farsi", "Trap"],
    "behzad leito": ["Persian Hip Hop", "Rap Farsi", "Trap"],
    "poori": ["Persian Hip Hop", "Rap Farsi", "Drill"],
    "godpoori": ["Persian Hip Hop", "Rap Farsi", "Drill"],
    "hiphopologist": ["Persian Hip Hop", "Rap Farsi", "Drill"],
    "chvrsi": ["Persian Hip Hop", "Rap Farsi", "Trap"],
    "021kid": ["Persian Hip Hop", "Rap Farsi", "UK Drill"],

    # French Chanson & Pop
    "charles aznavour": ["Chanson", "French Pop", "Vocal Pop"],
    "edith piaf": ["Chanson", "French Pop", "Traditional Pop"],
    "jacques brel": ["Chanson", "French Pop"],
    "serge gainsbourg": ["Chanson", "French Pop", "Pop Rock"],
    "georges brassens": ["Chanson", "French Folk"],
    "yves montand": ["Chanson", "French Pop"],
    "leo ferre": ["Chanson", "French Pop"],
    "dalida": ["Chanson", "French Pop", "Disco"],
    "joe dassin": ["Chanson", "French Pop"],
    "stromae": ["Electropop", "French Pop", "Hip-Hop"],
    "indila": ["French Pop", "World", "R&B"],

    # J-Pop / City Pop / Japanese
    "anri": ["City Pop", "J-Pop", "Japanese Funk"],
    "miki matsubara": ["City Pop", "J-Pop", "Japanese Disco"],
    "tatsuro yamashita": ["City Pop", "J-Pop", "Funk"],
    "mariya takeuchi": ["City Pop", "J-Pop"],
    "taeko onuki": ["City Pop", "J-Pop"],
    "creepy nuts": ["J-Pop", "Japanese Hip Hop", "Hip-Hop/Rap"],
    "yoasobi": ["J-Pop", "Electropop", "Anisong"],
    "kenshi yonezu": ["J-Pop", "J-Rock", "Alternative Rock"],
    "ado": ["J-Pop", "J-Rock", "Electropop"],
    "king gnu": ["J-Rock", "J-Pop", "Alternative Rock"],
    "fujii kaze": ["J-Pop", "R&B", "Soul"],
    "aimyon": ["J-Pop", "J-Rock", "Folk Rock"],
    "eve": ["J-Pop", "J-Rock", "Anisong"],
    "wurts": ["J-Pop", "Indie Rock", "Alternative Rock"],
    "one ok rock": ["J-Rock", "Alternative Rock", "Post-Hardcore"],
    "radwimps": ["J-Rock", "J-Pop", "Alternative Rock"],
    "l'arc-en-ciel": ["J-Rock", "Alternative Rock"],
    "x japan": ["Heavy Metal", "Speed Metal", "J-Rock"],
    "babymetal": ["Kawaii Metal", "Heavy Metal", "J-Pop"],
    "vaundy": ["J-Pop", "J-Rock", "R&B"],
    "lisa": ["J-Pop", "Anisong", "J-Rock"],
    "official hige dandism": ["J-Pop", "Pop Rock"],
    "asian kung-fu generation": ["J-Rock", "Alternative Rock"],

    # Metal / Hard Rock Legends
    "metallica": ["Thrash Metal", "Heavy Metal", "Metal", "Hard Rock"],
    "iron maiden": ["Heavy Metal", "Metal", "Power Metal"],
    "judas priest": ["Heavy Metal", "Metal", "Speed Metal"],
    "black sabbath": ["Heavy Metal", "Doom Metal", "Hard Rock"],
    "megadeth": ["Thrash Metal", "Speed Metal", "Metal"],
    "slayer": ["Thrash Metal", "Speed Metal", "Metal"],
    "pantera": ["Groove Metal", "Thrash Metal", "Heavy Metal"],
    "anthrax": ["Thrash Metal", "Heavy Metal", "Metal"],
    "motorhead": ["Heavy Metal", "Hard Rock", "Speed Metal"],
    "dio": ["Heavy Metal", "Hard Rock", "Power Metal"],
    "ozzy osbourne": ["Heavy Metal", "Hard Rock"],
    "system of a down": ["Nu Metal", "Alternative Metal", "Hard Rock"],
    "slipknot": ["Nu Metal", "Alternative Metal", "Heavy Metal"],
    "korn": ["Nu Metal", "Alternative Metal"],
    "linkin park": ["Nu Metal", "Alternative Rock", "Electronic Rock"],
    "rammstein": ["Industrial Metal", "Neue Deutsche Härte", "Metal"],
    "tool": ["Progressive Metal", "Alternative Metal", "Art Rock"],
    "avenged sevenfold": ["Heavy Metal", "Hard Rock", "Metalcore"],
    "disturbed": ["Heavy Metal", "Nu Metal", "Hard Rock"],
    "deftones": ["Alternative Metal", "Nu Metal", "Shoegaze"],
    "gojira": ["Progressive Metal", "Death Metal", "Groove Metal"],
    "nightwish": ["Symphonic Metal", "Power Metal"],
    "opeth": ["Progressive Metal", "Death Metal", "Progressive Rock"],
    "sepultura": ["Thrash Metal", "Groove Metal", "Death Metal"],

    # Rock / Grunge / Alternative / Classic Rock
    "nirvana": ["Grunge", "Alternative Rock", "Rock"],
    "pearl jam": ["Grunge", "Alternative Rock", "Hard Rock"],
    "soundgarden": ["Grunge", "Alternative Metal", "Hard Rock"],
    "alice in chains": ["Grunge", "Alternative Metal", "Heavy Metal"],
    "led zeppelin": ["Hard Rock", "Classic Rock", "Blues Rock"],
    "pink floyd": ["Progressive Rock", "Psychedelic Rock", "Art Rock"],
    "queen": ["Classic Rock", "Glam Rock", "Pop Rock"],
    "the beatles": ["Rock", "Pop Rock", "Psychedelic Rock"],
    "the rolling stones": ["Rock", "Blues Rock", "Hard Rock"],
    "ac/dc": ["Hard Rock", "Classic Rock"],
    "guns n' roses": ["Hard Rock", "Heavy Metal", "Classic Rock"],
    "aerosmith": ["Hard Rock", "Classic Rock"],
    "deep purple": ["Hard Rock", "Heavy Metal", "Classic Rock"],
    "radiohead": ["Alternative Rock", "Art Rock", "Electronic"],
    "the doors": ["Psychedelic Rock", "Classic Rock"],
    "the who": ["Classic Rock", "Hard Rock"],
    "david bowie": ["Art Rock", "Glam Rock", "Pop Rock"],
    "fleetwood mac": ["Classic Rock", "Pop Rock", "Soft Rock"],
    "foo fighters": ["Alternative Rock", "Post-Grunge", "Hard Rock"],
    "green day": ["Punk Rock", "Pop Punk", "Alternative Rock"],
    "red hot chili peppers": ["Funk Rock", "Alternative Rock"],
    "arctic monkeys": ["Indie Rock", "Garage Rock", "Alternative Rock"],
    "the neighbourhood": ["Indie Pop", "Alternative Rock", "Dark Pop"],
    "two feet": ["Alternative", "Indie Rock", "Blues", "Electronic"],
    "muse": ["Alternative Rock", "Space Rock", "Progressive Rock"],
    "the strokes": ["Indie Rock", "Garage Rock"],
    "oasis": ["Britpop", "Rock", "Alternative Rock"],
    "coldplay": ["Alternative Rock", "Pop Rock", "Post-Britpop"],
    "u2": ["Rock", "Pop Rock", "Alternative Rock"],

    # Pop / Dance / Synthpop
    "dua lipa": ["Pop", "Dance-Pop", "Nu-Disco"],
    "taylor swift": ["Pop", "Country Pop", "Singer-Songwriter"],
    "billie eilish": ["Alternative Pop", "Electropop", "Dark Pop"],
    "lana del rey": ["Dream Pop", "Baroque Pop", "Sadcore", "Alternative"],
    "ariana grande": ["Pop", "R&B", "Dance-Pop"],
    "lady gaga": ["Pop", "Dance-Pop", "Electropop"],
    "katy perry": ["Pop", "Dance-Pop"],
    "rihanna": ["Pop", "R&B", "Dance-Pop"],
    "beyonce": ["R&B", "Pop", "Hip-Hop"],
    "bruno mars": ["Pop", "Funk", "R&B/Soul"],
    "michael jackson": ["Pop", "R&B", "Funk", "Dance-Pop"],
    "madonna": ["Pop", "Dance-Pop", "Electropop"],
    "britney spears": ["Pop", "Dance-Pop"],
    "isabel larosa": ["Dark Pop", "Indie Pop", "Alternative Pop"],
    "thomas day": ["Pop", "Singer-Songwriter", "Acoustic Pop"],
    "ed sheeran": ["Pop", "Acoustic Pop", "Singer-Songwriter"],
    "adele": ["Soul", "Pop", "Vocal Pop"],
    "sam smith": ["Soul", "Pop"],
    "sia": ["Pop", "Electropop"],
    "shakira": ["Latin Pop", "Pop", "Dance-Pop"],

    # Hip-Hop / Rap / Trap / R&B
    "metro boomin": ["Hip-Hop/Rap", "Trap", "Southern Hip-Hop"],
    "the weeknd": ["R&B/Soul", "Contemporary R&B", "Synthpop", "Pop"],
    "travis scott": ["Hip-Hop/Rap", "Trap", "Psychedelic Rap"],
    "drake": ["Hip-Hop/Rap", "Contemporary R&B", "Pop Rap"],
    "kendrick lamar": ["Hip-Hop/Rap", "Conscious Hip-Hop", "West Coast Rap"],
    "eminem": ["Hip-Hop/Rap", "Hardcore Hip-Hop"],
    "kanye west": ["Hip-Hop/Rap", "Experimental Hip-Hop", "Pop"],
    "2pac": ["Hip-Hop/Rap", "West Coast Rap", "Gangsta Rap"],
    "the notorious b.i.g.": ["Hip-Hop/Rap", "East Coast Rap", "Gangsta Rap"],
    "snoop dogg": ["Hip-Hop/Rap", "West Coast Rap", "G-Funk"],
    "dr. dre": ["Hip-Hop/Rap", "West Coast Rap", "G-Funk"],
    "50 cent": ["Hip-Hop/Rap", "Gangsta Rap"],
    "jay-z": ["Hip-Hop/Rap", "East Coast Rap"],
    "j. cole": ["Hip-Hop/Rap", "Conscious Hip-Hop"],
    "post malone": ["Hip-Hop/Rap", "Pop", "Trap"],
    "juice wrld": ["Hip-Hop/Rap", "Emo Rap", "Trap"],
    "xxxtentacion": ["Hip-Hop/Rap", "Emo Rap", "Alternative Rock"],
    "lil uzi vert": ["Hip-Hop/Rap", "Trap", "Emo Rap"],
    "future": ["Hip-Hop/Rap", "Trap", "Southern Hip-Hop"],
    "21 savage": ["Hip-Hop/Rap", "Trap", "Gangsta Rap"],
    "playboi carti": ["Hip-Hop/Rap", "Rage", "Trap"],
    "asap rocky": ["Hip-Hop/Rap", "Cloud Rap", "East Coast Rap"],
    "frank ocean": ["Contemporary R&B", "Neo-Soul", "Alternative R&B"],
    "sza": ["Contemporary R&B", "Neo-Soul", "Pop"],
    "daniel caesar": ["Contemporary R&B", "Soul"],
    "brent faiyaz": ["Contemporary R&B", "R&B/Soul"],
    "steve lacy": ["R&B", "Indie Rock", "Neo-Soul"],
}

# Standardized synonyms & mappings
GENRE_SYNONYMS: Dict[str, str] = {
    "hip hop": "Hip-Hop",
    "hip-hop": "Hip-Hop",
    "rap": "Hip-Hop/Rap",
    "rap/hip hop": "Hip-Hop/Rap",
    "hip-hop/rap": "Hip-Hop/Rap",
    "r&b": "R&B/Soul",
    "r&b/soul": "R&B/Soul",
    "soul": "R&B/Soul",
    "alt rock": "Alternative Rock",
    "alt-rock": "Alternative Rock",
    "alternative": "Alternative Rock",
    "hard-rock": "Hard Rock",
    "j pop": "J-Pop",
    "j-pop": "J-Pop",
    "k pop": "K-Pop",
    "k-pop": "K-Pop",
    "french pop": "French Pop",
    "farsi": "Persian Pop",
    "worldwide": "World",
    "world music": "World",
    "dance": "Dance-Pop",
    "electro": "Electronic",
    "edm": "EDM",
    "synthpop": "Synthpop",
    "synth-pop": "Synthpop",
    "soundtracks": "Soundtrack",
    "asian music": "East Asian",
}

# Blacklist of noise or non-genre categories
GENRE_BLACKLIST: Set[str] = {
    "audio", "music", "sound", "track", "unknown", "films/games", "spoken word",
    "other", "various", "general", "sound clip", "default"
}


def format_genre_token(token: str) -> str:
    """Properly formats and capitalizes genre strings including acronyms and hyphens."""
    if not token:
        return ""
    clean = token.strip()
    low = clean.lower()

    if low in GENRE_SYNONYMS:
        return GENRE_SYNONYMS[low]

    # Handle special case acronyms
    acronym_map = {
        "r&b": "R&B",
        "edm": "EDM",
        "idm": "IDM",
        "j-pop": "J-Pop",
        "k-pop": "K-Pop",
        "j-rock": "J-Rock",
        "uk": "UK",
        "us": "US",
        "ost": "OST"
    }
    if low in acronym_map:
        return acronym_map[low]

    # Split by spaces and hyphens to preserve proper title casing
    def cap_word(w: str) -> str:
        w_low = w.lower()
        if w_low in acronym_map:
            return acronym_map[w_low]
        if w_low in ("and", "of", "the", "in", "de", "la", "du", "von"):
            return w_low
        return w.capitalize()

    # Handle hyphens
    if "-" in clean and "/" not in clean:
        parts = [cap_word(p) for p in clean.split("-")]
        return "-".join(parts)

    # Handle slashes (e.g. Hip-Hop/Rap)
    if "/" in clean:
        parts = [format_genre_token(p) for p in clean.split("/")]
        return "/".join(parts)

    words = clean.split()
    return " ".join(cap_word(w) for w in words)


class GenreResolver:
    """
    Multi-source, multi-category genre resolver.
    Queries:
    1. In-memory & Persistent Disk Cache
    2. Curated artist/genre knowledge base (covering 100+ Persian, Rock, Metal, J-Pop, etc. styles)
    3. Deezer API (Free, high-speed track & album genres)
    4. iTunes Search API (Track primaryGenreName + Artist primaryGenreName)
    5. Deduplication, synthesis, and canonical tag formatting
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(GenreResolver, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "SpotifyDownloader/1.4.2 (Windows NT 10.0; Win64; x64)"
        })
        self._artist_cache: Dict[str, List[str]] = {}
        self._track_cache: Dict[str, List[str]] = {}
        self._dirty = False
        self._cache_file = os.path.join(str(get_cache_dir()), "genre_cache.json")
        self._load_cache()

    def _load_cache(self):
        if os.path.isfile(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._artist_cache = data.get("artists", {})
                    self._track_cache = data.get("tracks", {})
                    logger.debug(f"Loaded {len(self._artist_cache)} artists and {len(self._track_cache)} tracks from genre cache.")
            except Exception as e:
                logger.debug(f"Could not load genre cache: {e}")

    def _save_cache(self, force: bool = False):
        """Atomically saves genre cache to disk using temporary file replacement."""
        if not self._dirty and not force:
            return
        tmp_file = f"{self._cache_file}.tmp"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._cache_file)), exist_ok=True)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "artists": self._artist_cache,
                    "tracks": self._track_cache
                }, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self._cache_file)
            self._dirty = False
            logger.debug("Successfully saved genre cache to disk.")
        except Exception as e:
            logger.debug(f"Could not save genre cache: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    def save_cache(self):
        """Public method to flush cached genres to disk."""
        self._save_cache(force=True)

    def resolve(self, artist: str, title: str = "", album: str = "") -> List[str]:
        """
        Resolves ALL applicable genres for the given song/artist.
        Returns a sorted, deduplicated list of pristine genres.
        """
        artist = (artist or "").strip()
        title = (title or "").strip()
        album = (album or "").strip()

        if not artist and not title:
            return []

        track_key = f"{artist.lower()} - {title.lower()}" if title else ""
        artist_key = artist.lower()

        # 1. Check in-memory track cache
        if track_key and track_key in self._track_cache:
            return list(self._track_cache[track_key])

        # 2. Collect candidate genres from all sources
        found_genres: Set[str] = set()

        # Source A: Curated Knowledge Base
        for cur_artist, genres in CURATED_ARTIST_GENRES.items():
            if cur_artist in artist_key or artist_key in cur_artist:
                for g in genres:
                    fmt = format_genre_token(g)
                    if fmt:
                        found_genres.add(fmt)
                break

        # Check artist cache
        if artist_key in self._artist_cache:
            for g in self._artist_cache[artist_key]:
                fmt = format_genre_token(g)
                if fmt:
                    found_genres.add(fmt)

        # Source B: Deezer Track & Album Lookup
        deezer_genres = self._query_deezer(artist, title)
        for g in deezer_genres:
            fmt = format_genre_token(g)
            if fmt:
                found_genres.add(fmt)

        # Source C: iTunes Search API Lookup
        itunes_genres = self._query_itunes(artist, title)
        for g in itunes_genres:
            fmt = format_genre_token(g)
            if fmt:
                found_genres.add(fmt)

        # Source D: Additional artist lookup if still empty or limited
        if len(found_genres) < 2 and artist:
            itunes_artist_genres = self._query_itunes_artist(artist)
            for g in itunes_artist_genres:
                fmt = format_genre_token(g)
                if fmt:
                    found_genres.add(fmt)

        # Filter out blacklisted noise tokens
        valid_genres = [
            g for g in found_genres
            if g and g.lower() not in GENRE_BLACKLIST and len(g) > 1
        ]

        # Sort deterministically
        final_list = sorted(list(set(valid_genres)))

        # Cache results and persist to disk
        new_cached = False
        if track_key and track_key not in self._track_cache:
            self._track_cache[track_key] = final_list
            new_cached = True

        if artist_key and final_list:
            if artist_key not in self._artist_cache:
                self._artist_cache[artist_key] = final_list
                new_cached = True
            else:
                merged = sorted(list(set(self._artist_cache[artist_key] + final_list)))
                if merged != self._artist_cache[artist_key]:
                    self._artist_cache[artist_key] = merged
                    new_cached = True

        if new_cached:
            self._dirty = True
            self._save_cache()

        return final_list

    def resolve_genre_string(self, artist: str, title: str = "", album: str = "", separator: str = "; ") -> str:
        """Convenience method returning a delimiter-separated genre string."""
        genres = self.resolve(artist, title, album)
        return separator.join(genres) if genres else ""

    def _query_deezer(self, artist: str, title: str) -> List[str]:
        if not artist and not title:
            return []
        query = f"{artist} {title}".strip()
        try:
            r = self._session.get("https://api.deezer.com/search", params={"q": query, "limit": 1}, timeout=4).json()
            if r.get("data"):
                track_data = r["data"][0]
                album_id = track_data.get("album", {}).get("id")
                if album_id:
                    al_r = self._session.get(f"https://api.deezer.com/album/{album_id}", timeout=4).json()
                    album_genres = al_r.get("genres", {}).get("data", [])
                    return [g.get("name") for g in album_genres if g.get("name")]
        except Exception as e:
            logger.debug(f"Deezer genre lookup error for '{query}': {e}")
        return []

    def _query_itunes(self, artist: str, title: str) -> List[str]:
        if not artist and not title:
            return []
        query = f"{artist} {title}".strip()
        try:
            r = self._session.get(
                "https://itunes.apple.com/search",
                params={"term": query, "entity": "song", "limit": 1},
                timeout=4
            ).json()
            if r.get("results"):
                item = r["results"][0]
                pg = item.get("primaryGenreName")
                return [pg] if pg else []
        except Exception as e:
            logger.debug(f"iTunes song genre lookup error for '{query}': {e}")
        return []

    def _query_itunes_artist(self, artist: str) -> List[str]:
        if not artist:
            return []
        try:
            r = self._session.get(
                "https://itunes.apple.com/search",
                params={"term": artist, "entity": "musicArtist", "limit": 1},
                timeout=4
            ).json()
            if r.get("results"):
                item = r["results"][0]
                pg = item.get("primaryGenreName")
                return [pg] if pg else []
        except Exception as e:
            logger.debug(f"iTunes artist genre lookup error for '{artist}': {e}")
        return []


_genre_resolver_instance: Optional[GenreResolver] = None

def get_genre_resolver() -> GenreResolver:
    global _genre_resolver_instance
    if _genre_resolver_instance is None:
        _genre_resolver_instance = GenreResolver()
    return _genre_resolver_instance
