import io
import os
import re
import base64
import threading
from typing import Dict, Optional
import requests
from PyQt6.QtCore import Qt, QRectF, QSize, QPointF, QModelIndex, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QPixmap, QImage,
    QPainterPath, QLinearGradient
)
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from core.queue_manager import QueueItem
from core.utils import format_duration, extract_embedded_cover
from gui.styles import (
    BG_CARD, BG_CARD_HOVER, BG_CARD_SELECTED, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, SPOTIFY_EMERALD,
    PROGRESS_BG, PROGRESS_FILL, STATUS_COLORS,
    BADGE_FLAC_16_BG, BADGE_FLAC_16_TEXT,
    BADGE_FLAC_24_BG, BADGE_FLAC_24_TEXT,
    BADGE_320K_BG, BADGE_320K_TEXT,
    BADGE_YTM_BG, BADGE_YTM_TEXT,
    BADGE_OPUS_BG, BADGE_OPUS_TEXT
)


import collections
from concurrent.futures import ThreadPoolExecutor
from gui.bridge import safe_emit

class ThumbnailSignalEmitter(QObject):
    sig_internal_loaded = pyqtSignal(str, object)  # key, QImage
    sig_loaded = pyqtSignal(str)                   # key


class ThumbnailCache:
    """Thread-safe bounded LRU in-memory cache for album artwork pixmaps."""
    _instance = None
    _lock = threading.Lock()
    MAX_CACHE_SIZE = 500

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.cache: collections.OrderedDict[str, QPixmap] = collections.OrderedDict()
            cls._instance.loading: set = set()
            cls._instance.emitter = ThumbnailSignalEmitter()
            cls._instance.emitter.sig_internal_loaded.connect(cls._instance._on_internal_loaded)
            cls._instance.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ThumbLoader")
        return cls._instance

    def _on_internal_loaded(self, key: str, img: Any):
        # Runs on GUI thread: safe to create QPixmap
        if img and hasattr(img, "isNull") and not img.isNull():
            try:
                pix = QPixmap.fromImage(img)
                with self._lock:
                    self.cache[key] = pix
                    self.cache.move_to_end(key)
                    while len(self.cache) > self.MAX_CACHE_SIZE:
                        self.cache.popitem(last=False)
                    self.loading.discard(key)
                self.emitter.sig_loaded.emit(key)
                return
            except Exception:
                pass
        with self._lock:
            self.loading.discard(key)

    def get(self, key: str) -> Optional[QPixmap]:
        if not key:
            return None
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def load_async(self, key: str):
        if not key:
            return
        with self._lock:
            if key in self.cache or key in self.loading:
                return
            self.loading.add(key)

        def worker():
            try:
                pix_bytes = None
                if os.path.isfile(key):
                    ext = os.path.splitext(key)[1].lower()
                    if ext in (".jpg", ".jpeg", ".png", ".webp"):
                        with open(key, "rb") as f_img:
                            pix_bytes = f_img.read()
                    else:
                        pix_bytes = extract_embedded_cover(key)
                elif key.startswith("http://") or key.startswith("https://"):
                    resp = requests.get(key, timeout=6)
                    if resp.status_code == 200:
                        pix_bytes = resp.content

                if pix_bytes:
                    img = QImage()
                    img.loadFromData(pix_bytes)
                    if not img.isNull():
                        scaled = img.scaled(
                            50, 50,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        safe_emit(self.emitter.sig_internal_loaded, key, scaled)
                        return
            except Exception:
                pass
            with self._lock:
                self.loading.discard(key)

        self.pool.submit(worker)


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
        self.thumb_cache.emitter.sig_loaded.connect(self._on_thumbnail_loaded)
        self.hoverRow = -1
        self.pressedRow = -1
        self.selectedRows = set()

        # Pre-cached fonts to avoid thousands of allocations per second and prevent PyQt6 TypeError
        self.font_icon = QFont("Segoe UI", 13)
        self.font_status = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        self.font_dur = QFont("Segoe UI", 9)
        self.font_badge = QFont("Segoe UI", 7, QFont.Weight.Bold)
        self.font_pct = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self.font_speed = QFont("Segoe UI", 8)
        self.font_title = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        self.fm_title = QFontMetrics(self.font_title)
        self.font_sub = QFont("Segoe UI", 9)
        self.fm_sub = QFontMetrics(self.font_sub)

        # Throttled timer to batch viewport updates during rapid thumbnail decodes
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(40)
        self._thumb_timer.timeout.connect(self._do_viewport_update)

    def _on_thumbnail_loaded(self, key: str):
        if not self._thumb_timer.isActive():
            self._thumb_timer.start()

    def _do_viewport_update(self):
        p = self.parent()
        if p:
            if hasattr(p, "viewport"):
                p.viewport().update()
            elif hasattr(p, "table") and hasattr(p.table, "viewport"):
                p.table.viewport().update()

    def setHoverRow(self, row: int):
        self.hoverRow = row
        p = self.parent()
        if p:
            if hasattr(p, "viewport"):
                p.viewport().update()
            elif hasattr(p, "table") and hasattr(p.table, "viewport"):
                p.table.viewport().update()

    def setPressedRow(self, row: int):
        self.pressedRow = row
        p = self.parent()
        if p:
            if hasattr(p, "viewport"):
                p.viewport().update()
            elif hasattr(p, "table") and hasattr(p.table, "viewport"):
                p.table.viewport().update()

    def setSelectedRows(self, rows):
        self.selectedRows = rows
        p = self.parent()
        if p:
            if hasattr(p, "viewport"):
                p.viewport().update()
            elif hasattr(p, "table") and hasattr(p.table, "viewport"):
                p.table.viewport().update()

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
        # Card Background with 8px rounded corners
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
        path.addRoundedRect(card_rect, 8, 8)
        painter.fillPath(path, QBrush(bg_color))
        if pen_color.alpha() > 0:
            painter.setPen(QPen(pen_color, 1.2))
            painter.drawPath(path)

        # 1. Album Artwork Thumbnail (50x50, vertically centered)
        thumb_y = card_rect.y() + (card_rect.height() - self.THUMB_SIZE) / 2.0
        thumb_rect = QRectF(card_rect.x() + 12, thumb_y, self.THUMB_SIZE, self.THUMB_SIZE)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 6, 6)

        thumb_key = item.output_path or item.track.cover_url or ""

        pixmap = self.thumb_cache.get(thumb_key) if thumb_key else None
        if pixmap:
            painter.save()
            painter.setClipPath(thumb_path)
            painter.drawPixmap(int(thumb_rect.x()), int(thumb_rect.y()), self.THUMB_SIZE, self.THUMB_SIZE, pixmap)
            painter.restore()
        else:
            painter.fillPath(thumb_path, QBrush(QColor("#282828")))
            painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
            painter.drawPath(thumb_path)
            painter.setPen(TEXT_MUTED)
            painter.setFont(self.font_icon)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "♫")

            if thumb_key:
                self.thumb_cache.load_async(thumb_key)

        # 2. Rightmost Status Pill (92x24)
        status_w = 92
        status_h = 24
        status_rect = QRectF(card_rect.right() - status_w - 14, card_rect.y() + (card_rect.height() - status_h) / 2.0, status_w, status_h)
        bg_status, fg_status = STATUS_COLORS.get(item.status, STATUS_COLORS["Queued"])

        status_path = QPainterPath()
        status_path.addRoundedRect(status_rect, 12, 12)
        painter.fillPath(status_path, QBrush(bg_status))
        painter.setPen(QPen(fg_status, 0.8))
        painter.drawPath(status_path)

        display_status = "✓ Completed" if item.status == "Completed" else item.status
        painter.setPen(fg_status)
        painter.setFont(self.font_status)
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignCenter, display_status)

        # 3. Middle Section: Dynamic layout based on status
        status_left = status_rect.left() - 14
        dur_str = format_duration(item.track.duration_ms)
        middle_left = status_left

        if item.status == "Completed":
            # Completed: Show Duration & Quality Badge cleanly (No duplicate progress bar)
            dur_w = 46
            dur_rect = QRectF(status_left - dur_w, card_rect.y(), dur_w, card_rect.height())
            painter.setPen(TEXT_SECONDARY)
            painter.setFont(self.font_dur)
            painter.drawText(dur_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur_str)
            middle_left = dur_rect.left()

            if item.quality_badge:
                badge_w = 86
                badge_h = 20
                badge_rect = QRectF(dur_rect.left() - badge_w - 10, card_rect.y() + (card_rect.height() - badge_h) / 2.0, badge_w, badge_h)
                badge_bg, badge_fg = self._get_badge_colors(item.quality_badge)

                b_path = QPainterPath()
                b_path.addRoundedRect(badge_rect, 4, 4)
                painter.fillPath(b_path, QBrush(badge_bg))
                painter.setPen(QPen(badge_fg, 0.8))
                painter.drawPath(b_path)

                painter.setPen(badge_fg)
                painter.setFont(self.font_badge)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, item.quality_badge)
                middle_left = badge_rect.left()

        elif item.status in ("Downloading", "Resolving"):
            # Downloading / Resolving: Show Progress Bar, Percentage, Speed & ETA
            center_w = 160
            center_x = status_left - center_w
            middle_left = center_x

            # Percentage text on top right
            pct_val = max(0.0, min(100.0, item.progress_percent))
            pct_str = f"{int(pct_val)}%"
            pct_rect = QRectF(center_x + center_w - 45, card_rect.y() + 11, 45, 18)
            painter.setPen(SPOTIFY_EMERALD)
            painter.setFont(self.font_pct)
            painter.drawText(pct_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct_str)

            # Quality badge on top left if available
            if item.quality_badge:
                badge_w = 80
                badge_h = 17
                badge_rect = QRectF(center_x, card_rect.y() + 11, badge_w, badge_h)
                badge_bg, badge_fg = self._get_badge_colors(item.quality_badge)
                b_path = QPainterPath()
                b_path.addRoundedRect(badge_rect, 3, 3)
                painter.fillPath(b_path, QBrush(badge_bg))
                painter.setPen(QPen(badge_fg, 0.8))
                painter.drawPath(b_path)
                painter.setPen(badge_fg)
                painter.setFont(self.font_badge)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, item.quality_badge)

            # Sleek progress track
            prog_rect = QRectF(center_x, card_rect.y() + 33, center_w, 5)
            prog_path = QPainterPath()
            prog_path.addRoundedRect(prog_rect, 2.5, 2.5)
            painter.fillPath(prog_path, QBrush(PROGRESS_BG))

            if pct_val > 0.0:
                fill_w = max(4.0, (pct_val / 100.0) * center_w)
                fill_rect = QRectF(center_x, card_rect.y() + 33, fill_w, 5)
                f_path = QPainterPath()
                f_path.addRoundedRect(fill_rect, 2.5, 2.5)
                painter.fillPath(f_path, QBrush(PROGRESS_FILL))

            # Speed and ETA below bar
            speed_text = f"{item.speed_str} • {item.eta_str}" if item.speed_str else "Connecting to stream..."
            painter.setPen(TEXT_MUTED)
            painter.setFont(self.font_speed)
            speed_rect = QRectF(center_x, card_rect.y() + 43, center_w, 16)
            painter.drawText(speed_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, speed_text)

        else:
            # Queued, Paused, Stopped, Failed: Show Duration & optional Badge
            dur_w = 46
            dur_rect = QRectF(status_left - dur_w, card_rect.y(), dur_w, card_rect.height())
            painter.setPen(TEXT_MUTED)
            painter.setFont(self.font_dur)
            painter.drawText(dur_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur_str)
            middle_left = dur_rect.left()

            if item.quality_badge:
                badge_w = 86
                badge_h = 20
                badge_rect = QRectF(dur_rect.left() - badge_w - 10, card_rect.y() + (card_rect.height() - badge_h) / 2.0, badge_w, badge_h)
                badge_bg, badge_fg = self._get_badge_colors(item.quality_badge)

                b_path = QPainterPath()
                b_path.addRoundedRect(badge_rect, 4, 4)
                painter.fillPath(b_path, QBrush(badge_bg))
                painter.setPen(QPen(badge_fg, 0.8))
                painter.drawPath(b_path)

                painter.setPen(badge_fg)
                painter.setFont(self.font_badge)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, item.quality_badge)
                middle_left = badge_rect.left()

        # 4. Title & Artist Text Section
        text_x = thumb_rect.right() + 14
        text_max_right = middle_left - 14
        text_w = max(60.0, text_max_right - text_x)

        # Track Title
        painter.setPen(TEXT_PRIMARY)
        painter.setFont(self.font_title)

        display_title = item.track.title
        if getattr(item.track, "collection_type", "") == "album" and getattr(item.track, "track_number", 0) > 0:
            if not re.match(r"^\d{1,3}[\s.\-_]+", display_title):
                display_title = f"{item.track.track_number:02d}. {display_title}"
        elided_title = self.fm_title.elidedText(display_title, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(int(text_x), int(card_rect.y() + 26), elided_title)

        # Artist & Album Subtitle
        artist_name = item.track.artist_str
        album_name = item.track.album
        if album_name and album_name.lower() not in ("spotify playlist", "unknown album", "singles", "downloads", "") and album_name.lower() != display_title.lower():
            sub_text = f"{artist_name}   •   {album_name}"
        else:
            sub_text = artist_name

        painter.setPen(TEXT_SECONDARY)
        painter.setFont(self.font_sub)
        elided_sub = self.fm_sub.elidedText(sub_text, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(int(text_x), int(card_rect.y() + 48), elided_sub)

        painter.restore()

    def _get_badge_colors(self, quality_badge: str):
        qb = quality_badge.lower()
        if "24" in qb:
            return BADGE_FLAC_24_BG, BADGE_FLAC_24_TEXT
        elif "16" in qb or "flac" in qb:
            return BADGE_FLAC_16_BG, BADGE_FLAC_16_TEXT
        elif "320" in qb:
            return BADGE_320K_BG, BADGE_320K_TEXT
        elif "opus" in qb:
            return BADGE_OPUS_BG, BADGE_OPUS_TEXT
        else:
            return BADGE_YTM_BG, BADGE_YTM_TEXT
