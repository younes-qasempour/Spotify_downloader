"""
Visual Design Tokens and Theme Constants for Spotify Downloader Fluent UI.
"""
from PyQt6.QtGui import QColor

# Accent & Brand Colors
SPOTIFY_EMERALD = QColor("#1DB954")
SPOTIFY_DARK_EMERALD = QColor("#14833B")
SPOTIFY_LIGHT_EMERALD = QColor("#1ED760")

# Backgrounds (Dark Mode)
BG_PRIMARY = QColor("#121212")
BG_SECONDARY = QColor("#181818")
BG_CARD = QColor("#242424")
BG_CARD_HOVER = QColor("#2E2E2E")
BG_CARD_SELECTED = QColor("#383838")
BORDER_SUBTLE = QColor("#333333")

# Text Colors
TEXT_PRIMARY = QColor("#FFFFFF")
TEXT_SECONDARY = QColor("#A7A7A7")
TEXT_MUTED = QColor("#727272")

# Quality Badges
BADGE_FLAC_16_BG = QColor(212, 175, 55, 45)      # Amber / Gold Tint
BADGE_FLAC_16_TEXT = QColor("#F5C518")

BADGE_FLAC_24_BG = QColor(157, 78, 221, 45)     # Purple Tint
BADGE_FLAC_24_TEXT = QColor("#C77DFF")

BADGE_320K_BG = QColor(29, 185, 84, 45)         # Spotify Green Tint
BADGE_320K_TEXT = QColor("#1ED760")

BADGE_YTM_BG = QColor(255, 71, 126, 45)          # Coral Tint
BADGE_YTM_TEXT = QColor("#FF758F")

# Status Pill Colors
STATUS_COLORS = {
    "Queued": (QColor(136, 136, 136, 40), QColor("#AAAAAA")),
    "Resolving": (QColor(59, 130, 246, 40), QColor("#60A5FA")),
    "Downloading": (QColor(16, 185, 129, 40), QColor("#34D399")),
    "Tagging": (QColor(245, 158, 11, 40), QColor("#FBBF24")),
    "Fetching Lyrics": (QColor(139, 92, 246, 40), QColor("#A78BFA")),
    "Completed": (QColor(29, 185, 84, 40), QColor("#1ED760")),
    "Paused": (QColor(234, 179, 8, 40), QColor("#EAB308")),
    "Stopped": (QColor(249, 115, 22, 40), QColor("#F97316")),
    "Failed": (QColor(239, 68, 68, 40), QColor("#F87171")),
    "Cancelled": (QColor(107, 114, 128, 40), QColor("#9CA3AF")),
}

# Progress Bar
PROGRESS_BG = QColor("#2A2A2A")
PROGRESS_FILL = QColor("#1DB954")
