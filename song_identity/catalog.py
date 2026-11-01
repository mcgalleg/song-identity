"""The songs this tool knows how to recognize."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Song:
    id: int
    composer: str
    title: str
    chapter: str
    short: str  # compact name for the menu bar
    url: str = ""  # recording the fingerprints are learned from
    end: int | None = None  # only learn the first N seconds of that recording

    @property
    def label(self) -> str:
        return f"#{self.id} {self.composer} – {self.title} (Ch. {self.chapter})"


SONGS: list[Song] = [
    Song(1, "Tchaikovsky", "The Nutcracker, Dance of the Sugar Plum Fairy", "49", "Sugar Plum Fairy", "https://www.youtube.com/watch?v=zV1qLYukTH8"),
    Song(2, "Tchaikovsky", "The Nutcracker, Trepak", "49", "Trepak", "https://www.youtube.com/watch?v=z2ISRMSIyX8"),
    Song(3, "Puccini", 'Madame Butterfly, "Un bel dì"', "50", "Un bel dì", "https://www.youtube.com/watch?v=c-r2vu4t9-g"),
    Song(4, "Debussy", 'Prelude to "The Afternoon of a Faun"', "51", "Afternoon of a Faun", "https://www.youtube.com/watch?v=Y9iDOt2WbjY"),
    # video is the whole quartet; movement I is 0:00-9:03
    Song(5, "Dvořák", "String Quartet in F Major, Op. 96 (American), I", "52", "American Quartet I", "https://www.youtube.com/watch?v=_b_rwtDlUXA", end=543),
    Song(6, "Spiritual", "Swing Low, Sweet Chariot (arr. Fisk)", "53", "Swing Low (Fisk)", "https://www.youtube.com/watch?v=GUvBGZnL9rE"),
    Song(7, "Spiritual", "Swing Low, Sweet Chariot (arr. Burleigh)", "53", "Swing Low (Burleigh)", "https://www.youtube.com/watch?v=yeaMOAwYc5M"),
    Song(8, "Joplin", "Maple Leaf Rag", "54", "Maple Leaf Rag", "https://www.youtube.com/watch?v=bCxLAr_bwpA"),
    Song(9, "Brahms", "A German Requiem, IV", "48", "German Requiem IV", "https://www.youtube.com/watch?v=Fc3v6mded4g"),
    Song(10, "Brahms", "Symphony No. 3 in F Major, III", "45", "Brahms Sym. 3, III", "https://www.youtube.com/watch?v=-JXvjejaVEc"),
]

BY_ID: dict[int, Song] = {s.id: s for s in SONGS}
