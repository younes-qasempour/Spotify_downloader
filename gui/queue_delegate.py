import io
import threading
from typing import Dict, Optional
import requests
from PyQt6.QtCore import Qt, QRectF, QSize, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QPixmap,
    QPainterPath, QLinearGradient
)
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PyQt6.QtCore import QModelIndex

from core.queue_manager import QueueItem
from core.utils import format_duration
from gui.styles import (
    BG_CARD, BG_CARD_HOVER, BG_CARD_SELECTED, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, SPOTIFY_EMERALD,
    PROGRESS_BG, PROGRESS_FILL, STATUS_COLORS,
    BADGE_FLAC_16_BG, BADGE_FLAC_16_TEXT,
    BADGE_FLAC_24_BG, BADGE_FLAC_24_TEXT,
    BADGE_320K_BG, BADGE_320K_TEXT,
    BADGE_YTM_BG, BADGE_YTM_TEXT
)


class ThumbnailCache:
    """Thread-safe in-memory cache for album artwork pixmaps."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.cache: Dict[str, QPixmap] = {}
            cls._instance.loading: set = set()
        return cls._instance

    def get(self, url: str) -> Optional[QPixmap]:
        with self._lock:
            return self.cache.get(url)

    def load_async(self, url: str, callback):
        if not url:
            return
        with self._lock:
            if url in self.cache or url in self.loading:
                return
            self.loading.add(url)

        def worker():
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    pix = QPixmap()
                    pix.loadFromData(resp.content)
                    if not pix.isNull():
                        scaled = pix.scaled(50, 50, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                        with self._lock:
                            self.cache[url] = scaled
                            self.loading.discard(url)
                        callback()
                        return
            except Exception:
                pass
            with self._lock:
                self.loading.discard(url)

        threading.Thread(target=worker, daemon=True).start()


class TrackCardDelegate(QStyledItemDelegate):
    """
    High-performance virtualized card delegate for track list.
    Paints rounded cover thumbnail, titles, quality badge, progress bar, and status pill.
    Compatible with QFluentWidgets TableView hover and press state management.
    """

    CARD_HEIGHT = 74
    THUMB_SIZE = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumb_cache = ThumbnailCache()
        self.hoverRow = -1
        self.pressedRow = -1
        self.selectedRows = set()

    def setHoverRow(self, row: int):
        self.hoverRow = row
        p = self.parent()
        if p and hasattr(p, "viewport"):
            p.viewport().update()

    def setPressedRow(self, row: int):
        self.pressedRow = row
        p = self.parent()
        if p and hasattr(p, "viewport"):
            p.viewport().update()

    def setSelectedRows(self, rows):
        self.selectedRows = rows
        p = self.parent()
        if p and hasattr(p, "viewport"):
            p.viewport().update()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.CARD_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        item: Optional[QueueItem] = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = option.rect
        # Draw Card Background with 10px rounded corners
        card_rect = QRectF(rect.x() + 6, rect.y() + 3, rect.width() - 12, rect.height() - 6)

        is_hover = (index.row() == getattr(self, 'hoverRow', -1)) or bool(option.state & option.state.State_MouseOver)
        is_selected = bool(option.state & option.state.State_Selected)

        if is_selected:
            bg_color = BG_CARD_SELECTED
            pen_color = SPOTIFY_EMERALD
        elif is_hover:
            bg_color = BG_CARD_HOVER
            pen_color = BORDER_SUBTLE
        else:
            bg_color = BG_CARD
            pen_color = QColor(0, 0, 0, 0)

        path = QPainterPath()
        path.addRoundedRect(card_rect, 10, 10)
        painter.fillPath(path, QBrush(bg_color))
        if pen_color.alpha() > 0:
            painter.setPen(QPen(pen_color, 1.2))
            painter.drawPath(path)

        # 1. Album Artwork Thumbnail (50x50 at x+18, y+9)
        thumb_rect = QRectF(card_rect.x() + 12, card_rect.y() + 9, self.THUMB_SIZE, self.THUMB_SIZE)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 6, 6)

        pixmap = self.thumb_cache.get(item.track.cover_url) if item.track.cover_url else None
        if pixmap:
            painter.save()
            painter.setClipPath(thumb_path)
            painter.drawPixmap(int(thumb_rect.x()), int(thumb_rect.y()), self.THUMB_SIZE, self.THUMB_SIZE, pixmap)
            painter.restore()
        else:
            # Sleek placeholder
            painter.fillPath(thumb_path, QBrush(QColor("#2E2E2E")))
            painter.setPen(QPen(TEXT_MUTED, 1))
            painter.drawPath(thumb_path)
            painter.setPen(TEXT_MUTED)
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "♫")

            # Asynchronously fetch thumbnail
            if item.track.cover_url:
                view = self.parent()
                self.thumb_cache.load_async(item.track.cover_url, lambda: view.viewport().update() if view else None)

        # Calculate horizontal positions
        right_margin = card_rect.right() - 14

        # 2. Status Pill (Width: 100px, Height: 24px at far right)
        status_w = 95
        status_h = 24
        status_rect = QRectF(right_margin - status_w, card_rect.y() + (card_rect.height() - status_h) / 2, status_w, status_h)
        bg_status, fg_status = STATUS_COLORS.get(item.status, STATUS_COLORS["Queued"])

        status_path = QPainterPath()
        status_path.addRoundedRect(status_rect, 12, 12)
        painter.fillPath(status_path, QBrush(bg_status))
        painter.setPen(QPen(fg_status, 1))
        painter.drawPath(status_path)

        painter.setPen(fg_status)
        font_status = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font_status)
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignCenter, item.status)

        # 3. Quality Badge & Progress Section (Between text and status pill)
        center_w = 170
        center_x = status_rect.left() - center_w - 16

        # Source Quality Badge (Width: 105px, Height: 20px)
        if item.quality_badge:
            badge_w = 105
            badge_h = 20
            badge_rect = QRectF(center_x, card_rect.y() + 11, badge_w, badge_h)
            badge_bg, badge_fg = self._get_badge_colors(item.quality_badge)

            b_path = QPainterPath()
            b_path.addRoundedRect(badge_rect, 4, 4)
            painter.fillPath(b_path, QBrush(badge_bg))
            painter.setPen(QPen(badge_fg, 0.8))
            painter.drawPath(b_path)

            painter.setPen(badge_fg)
            font_badge = QFont("Segoe UI", 7, QFont.Weight.Bold)
            painter.setFont(font_badge)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, item.quality_badge)

        # Progress Bar & Speed Text
        prog_rect = QRectF(center_x, card_rect.y() + 38, center_w, 6)
        prog_path = QPainterPath()
        prog_path.addRoundedRect(prog_rect, 3, 3)
        painter.fillPath(prog_path, QBrush(PROGRESS_BG))

        if item.progress_percent > 0.0:
            fill_w = max(4.0, (item.progress_percent / 100.0) * center_w)
            fill_rect = QRectF(center_x, card_rect.y() + 38, fill_w, 6)
            f_path = QPainterPath()
            f_path.addRoundedRect(fill_rect, 3, 3)
            painter.fillPath(f_path, QBrush(PROGRESS_FILL))

        # Speed and ETA text below or above progress bar
        speed_text = ""
        if item.status in ("Downloading", "Resolving") and item.speed_str:
            speed_text = f"{item.speed_str} • {item.eta_str}"
        elif item.status == "Completed":
            speed_text = "100%"

        if speed_text:
            painter.setPen(TEXT_MUTED)
            painter.setFont(QFont("Segoe UI", 8))
            text_rect = QRectF(center_x, card_rect.y() + 48, center_w, 16)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, speed_text)

        # 4. Title, Artist, and Duration Text
        text_x = thumb_rect.right() + 14
        text_w = center_x - text_x - 14

        # Title
        painter.setPen(TEXT_PRIMARY)
        font_title = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font_title)
        fm_title = QFontMetrics(font_title)
        elided_title = fm_title.elidedText(item.track.title, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(int(text_x), int(card_rect.y() + 25), elided_title)

        # Subtitle (Artist • Album • Duration)
        dur_str = format_duration(item.track.duration_ms)
        album_part = f" • {item.track.album}" if item.track.album else ""
        sub_text = f"{item.track.artist_str}{album_part} • {dur_str}"

        painter.setPen(TEXT_SECONDARY)
        font_sub = QFont("Segoe UI", 8)
        painter.setFont(font_sub)
        fm_sub = QFontMetrics(font_sub)
        elided_sub = fm_sub.elidedText(sub_text, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(int(text_x), int(card_rect.y() + 48), elided_sub)

        painter.restore()

    def _get_badge_colors(self, quality_badge: str):
        qb = quality_badge.lower()
        if "16" in qb:
            return BADGE_FLAC_16_BG, BADGE_FLAC_16_TEXT
        elif "24" in qb:
            return BADGE_FLAC_24_BG, BADGE_FLAC_24_TEXT
        elif "320" in qb:
            return BADGE_320K_BG, BADGE_320K_TEXT
        else:
            return BADGE_YTM_BG, BADGE_YTM_TEXT
