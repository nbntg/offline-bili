from __future__ import annotations

from pathlib import Path
from datetime import datetime
import shutil

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QPoint
from PySide6.QtGui import QColor, QCloseEvent, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .history import HistoryStore
from .bili23_adapter import Bili23Adapter, LoginThread, ParseLinksThread, VideoPreview
from .library import LibraryScan, ManagedLibrary, ManagedVideo
from .mpv_backend import MpvBackend, MpvUnavailableError
from .danmaku import DanmakuSettings, parse_bilibili_xml, render_ass
from .playback import SpeedController
from .settings import AppSettings, SettingsStore
from .download import DownloadCoordinator, DownloadRequest, DownloadThread
from .download_jobs import DownloadJob, DownloadJobStore
from .account import avatar_path, has_login, import_legacy_data, load_profile
from .subtitles import SubtitleSettings, render_bilibili_subtitle


PINK = "#fb7299"
DARK = "#18191c"
MUTED = "#9499a0"
SURFACE = "#f6f7f8"


def _human_count(value: int | float | None) -> str:
    number = float(value or 0)
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return str(int(number))


class PassivePlaybackBackend:
    def __init__(self):
        self.speed = 1.0
        self.paused = True
        self.volume = 100

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_volume(self, volume: int) -> None:
        self.volume = volume


class SpeedLabel(QLabel):
    speed_changed = Signal(float)
    reset_requested = Signal()

    def wheelEvent(self, event):
        steps = int(event.angleDelta().y() / 120)
        if steps:
            self.speed_changed.emit(float(steps))
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_requested.emit()
            event.accept()


class ChapterSlider(QSlider):
    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self._chapter_starts: list[float] = []
        self._chapter_duration = 0.0

    def set_chapters(self, chapters: list[dict], duration: float) -> None:
        starts = []
        for chapter in chapters[1:]:
            try:
                start = float(chapter.get("start", 0) or 0)
            except (TypeError, ValueError):
                continue
            if start > 0:
                starts.append(start)
        self._chapter_starts = starts
        self._chapter_duration = max(0.0, float(duration or 0))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._chapter_starts or self._chapter_duration <= 0:
            return
        painter = QPainter(self)
        painter.setPen(QColor(15, 15, 17, 210))
        left = 7
        usable = max(1, self.width() - left * 2)
        center = self.height() // 2
        for start in self._chapter_starts:
            x = left + round(min(1.0, start / self._chapter_duration) * usable)
            painter.drawLine(x, center - 4, x, center + 4)


class DownloadPage(QWidget):
    parse_requested = Signal(tuple)
    download_requested = Signal(object, int)
    retry_requested = Signal(object)
    remove_jobs_requested = Signal(object)
    cancel_active_requested = Signal()

    def __init__(self, job_store: DownloadJobStore, parent=None):
        super().__init__(parent)
        self.job_store = job_store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 22)
        layout.setSpacing(7)
        title = QLabel("下载视频")
        title.setObjectName("pageTitle")
        hint = QLabel("每行一个链接。这里只解析封面、标题、分 P 与可用画质，不会在线播放。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText("https://www.bilibili.com/video/BV...\nhttps://b23.tv/...")
        self.links.setMaximumHeight(56)

        self.parse_button = QPushButton("解析链接")
        self.parse_button.setObjectName("primary")
        self.parse_button.clicked.connect(self._submit)

        self.preview_panel = QFrame()
        self.preview_panel.setObjectName("downloadPreview")
        preview_layout = QHBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(16)
        self.preview_cover = QLabel()
        self.preview_cover.setObjectName("previewCover")
        self.preview_cover.setFixedSize(268, 151)
        self.preview_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_cover)
        details = QVBoxLayout()
        self.preview_title = QLabel()
        self.preview_title.setObjectName("previewTitle")
        self.preview_title.setWordWrap(True)
        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("muted")
        self.preview_stats = QLabel()
        self.preview_stats.setObjectName("muted")
        self.preview_description = QLabel()
        self.preview_description.setWordWrap(True)
        self.preview_description.setMaximumHeight(42)
        owner_row = QHBoxLayout()
        self.preview_avatar = QLabel()
        self.preview_avatar.setFixedSize(42, 42)
        self.preview_owner = QLabel()
        self.preview_owner.setObjectName("previewOwner")
        owner_row.addWidget(self.preview_avatar)
        owner_row.addWidget(self.preview_owner)
        owner_row.addStretch()
        details.addWidget(self.preview_title)
        details.addWidget(self.preview_meta)
        details.addWidget(self.preview_stats)
        details.addWidget(self.preview_description)
        details.addStretch()
        details.addLayout(owner_row)
        preview_layout.addLayout(details, 1)
        self.preview_panel.hide()

        self.result_title = QLabel()
        self.result_title.setObjectName("dialogTitle")
        self.result_title.hide()
        self.result_list = QListWidget()
        self.result_list.setMinimumHeight(155)
        self.result_list.setMaximumHeight(225)
        self.result_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.result_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.result_list.hide()
        self.select_all = QCheckBox("全选")
        self.select_all.setChecked(True)
        self.select_all.toggled.connect(self._toggle_all)
        self.select_all.hide()
        self.quality = QComboBox()
        self.quality.hide()
        self.download_button = QPushButton("加入下载队列")
        self.download_button.setObjectName("primary")
        self.download_button.clicked.connect(self._submit_download)
        self.download_button.hide()
        result_controls = QHBoxLayout()
        result_controls.addWidget(self.select_all)
        result_controls.addStretch()
        result_controls.addWidget(QLabel("画质"))
        result_controls.addWidget(self.quality)
        result_controls.addWidget(self.download_button)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addSpacing(8)
        layout.addWidget(self.links)
        parse_row = QHBoxLayout()
        parse_row.addStretch()
        parse_row.addWidget(self.parse_button)
        layout.addLayout(parse_row)
        layout.addWidget(self.preview_panel)
        layout.addWidget(self.result_title)
        layout.addWidget(self.result_list)
        layout.addLayout(result_controls)

        jobs_header = QHBoxLayout()
        jobs_title = QLabel("下载任务")
        jobs_title.setObjectName("sectionTitle")
        self.retry_button = QPushButton("重试未完成")
        self.remove_button = QPushButton("移除选中")
        self.cancel_button = QPushButton("取消当前下载")
        for button in (self.retry_button, self.remove_button, self.cancel_button):
            button.setObjectName("quiet")
        self.retry_button.clicked.connect(self._retry_jobs)
        self.remove_button.clicked.connect(self._remove_jobs)
        self.cancel_button.clicked.connect(self.cancel_active_requested)
        jobs_header.addWidget(jobs_title)
        jobs_header.addStretch()
        jobs_header.addWidget(self.retry_button)
        jobs_header.addWidget(self.remove_button)
        jobs_header.addWidget(self.cancel_button)
        self.jobs = QListWidget()
        self.jobs.setObjectName("jobList")
        self.jobs.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs.setMinimumHeight(78)
        self.jobs.setMaximumHeight(140)
        self.download_progress_label = QLabel()
        self.download_progress_label.setObjectName("muted")
        self.download_progress = QProgressBar()
        self.download_progress.setObjectName("downloadProgress")
        self.download_progress.setRange(0, 1000)
        self.download_progress.setTextVisible(False)
        self.download_notice = QLabel()
        self.download_notice.setObjectName("downloadNotice")
        self.download_notice.setWordWrap(True)
        self.download_progress_label.hide()
        self.download_progress.hide()
        self.download_notice.hide()
        layout.addSpacing(6)
        layout.addLayout(jobs_header)
        layout.addWidget(self.download_progress_label)
        layout.addWidget(self.download_progress)
        layout.addWidget(self.download_notice)
        layout.addWidget(self.jobs)
        layout.addStretch()
        self._previews: tuple[VideoPreview, ...] = ()
        self.reload_jobs()

    def _submit(self):
        links = tuple(line.strip() for line in self.links.toPlainText().splitlines() if line.strip())
        if not links:
            QMessageBox.information(self, "没有链接", "请至少粘贴一个 B 站视频链接。")
            return
        self.parse_requested.emit(links)

    def set_parsing(self, parsing: bool) -> None:
        self.parse_button.setEnabled(not parsing)
        self.parse_button.setText("正在解析…" if parsing else "解析链接")

    def show_error(self, message: str) -> None:
        self.set_parsing(False)
        QMessageBox.warning(self, "解析失败", message)

    def show_results(self, previews: tuple[VideoPreview, ...]) -> None:
        self._previews = previews
        self.set_parsing(False)
        if len(previews) == 1:
            preview = previews[0]
            self._show_preview(preview)
            if preview.collection_title:
                self.result_title.setText(f"{preview.collection_title} · 选择要下载的视频")
            else:
                self.result_title.setText("选择要下载的分 P")
        else:
            self.result_title.setText(f"已解析 {len(previews)} 个视频，请选择要下载的分 P")
            self._show_preview(previews[0])
        self.result_title.show()
        self.result_list.clear()
        quality_maps: list[dict[int, str]] = []
        for preview_index, preview in enumerate(previews):
            for part_index, part in enumerate(preview.parts):
                prefix = f"{preview.title} · " if len(previews) > 1 else ""
                section = f"{part.section_title}  ·  " if part.section_title else ""
                part_number = f"P{part.page}  " if not preview.collection_title else f"{part_index + 1}.  "
                item = QListWidgetItem(
                    f"{prefix}{section}{part_number}{part.title}    {_clock(part.duration)}"
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, (preview_index, part_index))
                item.setSizeHint(QSize(0, 38))
                self.result_list.addItem(item)
            quality_maps.append({quality.quality_id: quality.name for quality in preview.qualities})
        quality_ids = set.intersection(*(set(mapping) for mapping in quality_maps)) if quality_maps else set()
        if not quality_ids:
            quality_ids = set().union(*(set(mapping) for mapping in quality_maps)) if quality_maps else set()
        quality_names = {
            quality_id: next(
                mapping[quality_id] for mapping in quality_maps if quality_id in mapping
            )
            for quality_id in quality_ids
        }
        self.quality.clear()
        for index, (quality_id, name) in enumerate(sorted(quality_names.items(), reverse=True)):
            label = f"{name}（当前可用最高）" if index == 0 else name
            self.quality.addItem(label, quality_id)
        if self.quality.count():
            self.quality.setCurrentIndex(0)
        self.result_list.show()
        self.select_all.show()
        self.quality.show()
        self.download_button.show()

    def _show_preview(self, preview: VideoPreview) -> None:
        self.preview_title.setText(preview.title)
        published = datetime.fromtimestamp(preview.published_at).strftime("%Y-%m-%d %H:%M") if preview.published_at else ""
        meta = "  ·  ".join(item for item in (preview.category, published, " / ".join(preview.tags[:4])) if item)
        self.preview_meta.setText(meta)
        stats = preview.stats
        self.preview_stats.setText(
            "   ".join(
                (
                    f"{_human_count(stats.get('view'))} 播放",
                    f"{_human_count(stats.get('danmaku'))} 弹幕",
                    f"{_human_count(stats.get('like'))} 点赞",
                    f"{_human_count(stats.get('coin'))} 投币",
                    f"{_human_count(stats.get('favorite'))} 收藏",
                )
            )
        )
        self.preview_description.setText(preview.description or "暂无视频简介")
        self.preview_owner.setText(f"UP  {preview.owner_name or '未知 UP 主'}")
        self.preview_cover.setPixmap(
            _cover_pixmap(Path(preview.cover_path) if preview.cover_path else None, 268, 151)
        )
        avatar = QPixmap(preview.owner_face_path) if preview.owner_face_path else QPixmap()
        if not avatar.isNull():
            self.preview_avatar.setPixmap(
                avatar.scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.preview_avatar.clear()
        self.preview_panel.show()

    def _toggle_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.result_list.count()):
            self.result_list.item(index).setCheckState(state)

    def _submit_download(self) -> None:
        selected = []
        for index in range(self.result_list.count()):
            item = self.result_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                preview_index, part_index = item.data(Qt.ItemDataRole.UserRole)
                preview = self._previews[preview_index]
                selected.append((preview, preview.parts[part_index]))
        if not selected:
            QMessageBox.information(self, "没有选择", "请至少选择一个分 P。")
            return
        quality_id = int(self.quality.currentData()) if self.quality.count() else 80
        self.download_requested.emit(tuple(selected), quality_id)

    def set_downloading(self, current: int, total: int, percent: int, title: str) -> None:
        self.download_button.setEnabled(False)
        self.download_button.setText("正在下载")
        overall = ((current - 1) + max(0, min(100, percent)) / 100) / max(1, total)
        self.download_progress.setValue(round(overall * 1000))
        self.download_progress_label.setText(
            f"下载中 {current}/{total} · {percent}% · {title}"
        )
        self.download_progress_label.show()
        self.download_progress.show()
        self.download_notice.hide()

    def show_download_error(self, message: str) -> None:
        self.download_button.setEnabled(True)
        self.download_button.setText("加入下载队列")
        QMessageBox.warning(self, "下载失败", message)

    def download_finished(self, completed_count: int) -> None:
        self.download_button.setEnabled(True)
        self.download_button.setText("加入下载队列")
        if completed_count <= 0:
            self.download_progress_label.setText("下载未完成")
            self.download_progress.hide()
            self.download_notice.hide()
            self.reload_jobs()
            return
        self.download_progress.setValue(1000)
        self.download_progress_label.setText("下载任务已完成")
        self.download_notice.setText(
            f"✓ 已完成 {completed_count} 个离线视频包，并通过完整性校验。"
        )
        self.download_notice.show()
        self.reload_jobs()

    def reload_jobs(self) -> None:
        self.jobs.clear()
        labels = {"pending": "等待中", "running": "下载中", "failed": "失败", "completed": "已完成"}
        all_jobs = self.job_store.list_jobs()
        for job in all_jobs:
            detail = f" · {job.error}" if job.error else ""
            item = QListWidgetItem(
                f"{labels.get(job.status, job.status)}  {job.request.preview.title} · "
                f"P{job.request.part.page} {job.request.part.title}{detail}"
            )
            item.setData(Qt.ItemDataRole.UserRole, job.job_id)
            self.jobs.addItem(item)
        self.jobs.setVisible(bool(all_jobs))
        self.retry_button.setEnabled(any(job.status in {"pending", "failed"} for job in all_jobs))
        self.remove_button.setEnabled(bool(all_jobs))

    def _retry_jobs(self) -> None:
        jobs = tuple(job for job in self.job_store.list_jobs() if job.status in {"pending", "failed"})
        if jobs:
            self.retry_requested.emit(jobs)

    def _remove_jobs(self) -> None:
        job_ids = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.jobs.selectedItems())
        if job_ids:
            self.remove_jobs_requested.emit(job_ids)



class LoginDialog(QDialog):
    login_succeeded = Signal(object)

    def __init__(self, adapter: Bili23Adapter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录 B 站账号")
        self.setFixedSize(390, 430)
        self.adapter = adapter
        self.thread: LoginThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        title = QLabel("使用哔哩哔哩客户端扫码")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qrcode = QLabel("正在生成二维码…")
        self.qrcode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qrcode.setMinimumSize(190, 190)
        self.status = QLabel("登录信息只保存在这个程序文件夹中")
        self.status.setObjectName("muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.refresh_button = QPushButton("刷新二维码")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self._restart_login)
        self.refresh_button.hide()
        close_button = QPushButton("取消")
        close_button.setObjectName("quiet")
        close_button.clicked.connect(self.reject)

        layout.addWidget(title)
        layout.addWidget(self.qrcode, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.refresh_button)
        layout.addWidget(close_button)
        self._restart_login()

    def _restart_login(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)
        self.qrcode.clear()
        self.qrcode.setText("正在生成二维码…")
        self.status.setText("登录信息只保存在这个程序文件夹中")
        self.refresh_button.hide()
        self.thread = LoginThread(self.adapter, self)
        self.thread.qrcode_ready.connect(self._show_qrcode)
        self.thread.status_changed.connect(self._show_status)
        self.thread.succeeded.connect(self._login_succeeded)
        self.thread.failed.connect(self._login_failed)
        self.thread.start()

    def _show_qrcode(self, url: str) -> None:
        from qrcode import QRCode

        generator = QRCode(border=4)
        generator.add_data(url)
        generator.make(fit=True)
        matrix = generator.get_matrix()
        box_size = max(1, 180 // len(matrix))
        image_size = len(matrix) * box_size
        image = QImage(image_size, image_size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        for row_index, row in enumerate(matrix):
            for column_index, dark in enumerate(row):
                if dark:
                    painter.drawRect(
                        column_index * box_size,
                        row_index * box_size,
                        box_size,
                        box_size,
                    )
        painter.end()
        self.qrcode.setPixmap(
            QPixmap.fromImage(image).scaled(
                QSize(190, 190),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )
        self.status.setText("请扫码并在手机上确认登录")

    def _show_status(self, code: int, _message: str) -> None:
        status = {
            86101: "等待扫码…",
            86090: "已扫码，请在手机上确认",
            86038: "二维码已过期",
        }.get(code, "正在确认登录…")
        self.status.setText(status)
        self.refresh_button.setVisible(code == 86038)

    def _login_succeeded(self, profile: dict) -> None:
        self.login_succeeded.emit(profile)
        QMessageBox.information(self, "登录成功", f"已登录：{profile.get('username') or 'B 站账号'}")
        self.accept()

    def _login_failed(self, message: str) -> None:
        self.status.setText(message)
        self.refresh_button.show()

    def reject(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)
        super().reject()

    def accept(self) -> None:
        if self.thread is not None:
            self.thread.wait(2000)
        super().accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)
        super().closeEvent(event)


class EmptyState(QWidget):
    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("▶")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName("emptyIcon")
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setObjectName("emptyTitle")
        description = QLabel(detail)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setObjectName("muted")
        layout.addWidget(icon)
        layout.addSpacing(8)
        layout.addWidget(heading)
        layout.addWidget(description)


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _parse_timecode(value: str) -> float | None:
    text = value.split("/", 1)[0].strip()
    if not text:
        return None
    try:
        pieces = [int(piece) for piece in text.split(":")]
    except ValueError:
        return None
    if len(pieces) == 3:
        hours, minutes, seconds = pieces
    elif len(pieces) == 2:
        hours, minutes, seconds = 0, *pieces
    elif len(pieces) == 1:
        return float(pieces[0]) if pieces[0] >= 0 else None
    else:
        return None
    if min(hours, minutes, seconds) < 0 or minutes >= 60 or seconds >= 60:
        return None
    return float(hours * 3600 + minutes * 60 + seconds)


def _cover_pixmap(path: Path | None, width: int = 276, height: int = 155) -> QPixmap:
    source = QPixmap(str(path)) if path and path.is_file() else QPixmap()
    if source.isNull():
        source = QPixmap(width, height)
        source.fill(Qt.GlobalColor.darkGray)
        return source
    scaled = source.scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    return scaled.copy(max(0, (scaled.width() - width) // 2), max(0, (scaled.height() - height) // 2), width, height)


class VideoCard(QFrame):
    play_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, video: ManagedVideo, entry=None, selectable: bool = False, parent=None):
        super().__init__(parent)
        self.video = video
        self.selector: QCheckBox | None = None
        self.setObjectName("videoCard")
        self.setFixedWidth(282)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 8)
        layout.setSpacing(6)
        thumbnail = QFrame()
        thumbnail.setFixedSize(276, 155)
        stack = QStackedLayout(thumbnail)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        cover = QLabel()
        cover.setPixmap(_cover_pixmap(video.cover_path))
        stack.addWidget(cover)
        overlay = QWidget()
        overlay.setObjectName("cardOverlay")
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(7, 6, 7, 5)
        top = QHBoxLayout()
        if selectable:
            self.selector = QCheckBox()
            self.selector.setObjectName("cardSelector")
            top.addWidget(self.selector)
        top.addStretch()
        delete = QPushButton("×")
        delete.setObjectName("cardDelete")
        delete.setToolTip("删除观看记录" if selectable else "删除离线视频")
        delete.clicked.connect(lambda: self.delete_requested.emit(self.video))
        top.addWidget(delete)
        overlay_layout.addLayout(top)
        overlay_layout.addStretch()
        position = entry.position_seconds if entry else 0.0
        duration = entry.duration_seconds if entry and entry.duration_seconds > 0 else float(video.metadata.get("duration", 0) or 0)
        time_label = QLabel(f"{_clock(position)}/{_clock(duration)}")
        time_label.setObjectName("thumbnailTime")
        time_row = QHBoxLayout()
        time_row.addStretch()
        time_row.addWidget(time_label)
        overlay_layout.addLayout(time_row)
        stack.addWidget(overlay)
        stack.setCurrentWidget(overlay)
        layout.addWidget(thumbnail)
        progress = QProgressBar()
        progress.setObjectName("watchProgress")
        progress.setTextVisible(False)
        progress.setRange(0, 1000)
        progress.setValue(round(min(1.0, position / duration) * 1000) if duration else 0)
        progress.setFixedHeight(4)
        layout.addWidget(progress)
        title = QLabel(str(video.metadata.get("title", video.video_unit_id)))
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(46)
        owner = QLabel(f"UP  {video.metadata.get('owner_name') or '未知 UP 主'}")
        owner.setObjectName("cardMeta")
        layout.addWidget(title)
        layout.addWidget(owner)
        if entry is not None:
            when = datetime.fromtimestamp(entry.last_played_at).strftime("%m-%d %H:%M")
            state = "已看完" if entry.completed else f"看到 {_clock(position)}"
            meta = QLabel(f"{state}  ·  {when}")
            meta.setObjectName("cardMeta")
            layout.addWidget(meta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_requested.emit(self.video)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class VideoGrid(QScrollArea):
    def __init__(self, cards: list[VideoCard], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 8, 18)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(16)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3, Qt.AlignmentFlag.AlignTop)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        grid.setRowStretch((len(cards) + 2) // 3, 1)
        self.setWidget(content)


class LibraryPage(QWidget):
    play_requested = Signal(object)
    import_requested = Signal()
    delete_requested = Signal(object)

    def __init__(self, scan: LibraryScan, history: HistoryStore, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("媒体库")
        title.setObjectName("pageTitle")
        subtitle = QLabel(f"{len(scan.videos)} 个受管视频 · {len(scan.rejected)} 个文件包未通过校验")
        subtitle.setObjectName("muted")
        import_button = QPushButton("＋ 导入链接")
        import_button.setObjectName("primary")
        import_button.clicked.connect(self.import_requested)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(import_button)
        layout.addLayout(header)
        layout.addSpacing(18)

        if not scan.videos:
            layout.addWidget(
                EmptyState(
                    "还没有离线视频",
                    "导入明确的视频链接并下载完成后，经过完整性校验的内容才会出现在这里。",
                ),
                1,
            )
            return

        cards: list[VideoCard] = []
        for video in scan.videos:
            card = VideoCard(video, history.get(video.video_unit_id))
            card.play_requested.connect(self.play_requested)
            card.delete_requested.connect(self.delete_requested)
            cards.append(card)
        layout.addWidget(VideoGrid(cards), 1)


class HistoryPage(QWidget):
    play_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, history: HistoryStore, scan: LibraryScan, parent=None):
        super().__init__(parent)
        self.history = history
        self.video_map = {video.video_unit_id: video for video in scan.videos}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        header = QHBoxLayout()
        title = QLabel("历史记录")
        title.setObjectName("pageTitle")
        self.mark_watched = QPushButton("标为已看完")
        self.mark_unwatched = QPushButton("标为未看完")
        clear = QPushButton("清空历史")
        for button in (self.mark_watched, self.mark_unwatched, clear):
            button.setObjectName("quiet")
        self.mark_watched.clicked.connect(lambda: self._set_selected_completed(True))
        self.mark_unwatched.clicked.connect(lambda: self._set_selected_completed(False))
        clear.clicked.connect(self._clear)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.mark_watched)
        header.addWidget(self.mark_unwatched)
        header.addWidget(clear)
        layout.addLayout(header)
        layout.addSpacing(18)
        self.content_layout = layout
        self.grid: QWidget | None = None
        self.cards: list[VideoCard] = []
        self._reload()

    def _reload(self) -> None:
        if self.grid is not None:
            self.content_layout.removeWidget(self.grid)
            self.grid.deleteLater()
        entries = self.history.list_recent()
        self.cards = []
        for entry in entries:
            video = self.video_map.get(entry.video_unit_id)
            if video is None:
                continue
            card = VideoCard(video, entry, selectable=True)
            card.play_requested.connect(self.play_requested)
            card.delete_requested.connect(self.delete_requested)
            self.cards.append(card)
        self.grid = VideoGrid(self.cards) if self.cards else EmptyState(
            "还没有观看记录", "开始播放媒体库中的视频后，进度会自动出现在这里。"
        )
        self.content_layout.addWidget(self.grid, 1)
        empty = not self.cards
        self.mark_watched.setEnabled(not empty)
        self.mark_unwatched.setEnabled(not empty)

    def _set_selected_completed(self, completed: bool) -> None:
        for card in self.cards:
            if card.selector is not None and card.selector.isChecked():
                self.history.set_completed(card.video.video_unit_id, completed)
        self._reload()

    def _clear(self) -> None:
        if not self.history.list_recent():
            return
        answer = QMessageBox.question(self, "清空历史", "确定要清空全部观看记录吗？")
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self._reload()


class VideoSurface(QFrame):
    fullscreen_requested = Signal()
    activity = Signal()
    toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        self.activity.emit()
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        self.activity.emit()
        super().enterEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.fullscreen_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PlayerPage(QWidget):
    back_requested = Signal()
    fullscreen_requested = Signal()
    video_requested = Signal(object)

    def __init__(
        self,
        settings: AppSettings,
        settings_store: SettingsStore,
        tools_dir: Path,
        cache_dir: Path,
        history: HistoryStore,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.settings_store = settings_store
        self.tools_dir = tools_dir
        self.cache_dir = cache_dir
        self.history = history
        self.asset_dir = tools_dir.parent / "assets"
        self.backend = PassivePlaybackBackend()
        self._mpv: MpvBackend | None = None
        self._duration = 0.0
        self._seeking = False
        self._current_video: ManagedVideo | None = None
        self._position = 0.0
        self._last_saved_position = -5.0
        self._resume_position: float | None = None
        self._subtitle_index = 0
        self._paused = True
        self._fullscreen = False
        self.speed = SpeedController(self.backend)
        self.speed.set(settings.playback_speed)

        self._playlist: tuple[ManagedVideo, ...] = ()
        self._visible_playlist: tuple[ManagedVideo, ...] = ()
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(26, 18, 26, 22)
        self.root_layout.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(18)
        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(10)
        self.top_bar = QWidget()
        top = QVBoxLayout(self.top_bar)
        top.setContentsMargins(2, 0, 0, 0)
        top.setSpacing(5)
        self.title = QLabel("未选择视频")
        self.title.setObjectName("playerTitle")
        self.title_meta = QLabel("")
        self.title_meta.setObjectName("playerMeta")
        top.addWidget(self.title)
        top.addWidget(self.title_meta)
        left_column.addWidget(self.top_bar)

        self.video_surface = VideoSurface()
        self.video_surface.setObjectName("videoSurface")
        self.video_surface.fullscreen_requested.connect(self.fullscreen_requested)
        self.video_surface.activity.connect(self.show_player_controls)
        self.video_surface.toggle_requested.connect(self.toggle_pause)
        surface_layout = QVBoxLayout(self.video_surface)
        surface_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel("正在准备播放组件…")
        self.status.setObjectName("videoStatus")
        surface_layout.addWidget(self.status)
        self.player_stage = QFrame()
        self.player_stage.setObjectName("playerStage")
        self.player_stage.setMinimumHeight(360)
        stage_layout = QVBoxLayout(self.player_stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.addWidget(self.video_surface)
        self.fullscreen_title = QLabel("未选择视频", self.player_stage)
        self.fullscreen_title.setObjectName("fullscreenTitle")
        self.fullscreen_title.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.fullscreen_title.hide()
        left_column.addWidget(self.player_stage, 1)

        self.danmaku_bar = QFrame()
        self.danmaku_bar.setObjectName("danmakuBar")
        danmaku_bar_layout = QHBoxLayout(self.danmaku_bar)
        danmaku_bar_layout.setContentsMargins(14, 4, 10, 4)
        danmaku_bar_layout.setSpacing(12)
        self.danmaku_bar_toggle = QCheckBox("弹幕")
        self.danmaku_bar_toggle.setToolTip("开启/关闭弹幕（D）")
        self.danmaku_bar_toggle.setChecked(True)
        self.danmaku_bar_toggle.toggled.connect(self._toggle_danmaku_from_bar)
        self.danmaku_bar_status = QLabel("本地弹幕")
        self.danmaku_bar_status.setObjectName("muted")
        self.danmaku_bar_settings = QPushButton("⚙  弹幕设置")
        self.danmaku_bar_settings.setObjectName("danmakuBarButton")
        self.danmaku_bar_settings.clicked.connect(lambda: self._show_display_settings(0))
        danmaku_bar_layout.addWidget(self.danmaku_bar_toggle)
        danmaku_bar_layout.addWidget(self.danmaku_bar_status)
        danmaku_bar_layout.addStretch()
        danmaku_bar_layout.addWidget(self.danmaku_bar_settings)
        left_column.addWidget(self.danmaku_bar)
        body.addLayout(left_column, 2)
        self.info_panel = QFrame()
        self.info_panel.setObjectName("playerInfo")
        self.info_panel.setFixedWidth(320)
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)

        owner_card = QFrame()
        owner_card.setObjectName("ownerCard")
        owner_layout = QHBoxLayout(owner_card)
        owner_layout.setContentsMargins(12, 10, 12, 10)
        owner_layout.setSpacing(10)
        self.owner_avatar = QLabel()
        self.owner_avatar.setObjectName("ownerAvatar")
        self.owner_avatar.setFixedSize(48, 48)
        owner_text = QVBoxLayout()
        owner_text.setSpacing(2)
        self.owner = QLabel("未知 UP 主")
        self.owner.setObjectName("ownerName")
        owner_text.addWidget(self.owner)
        owner_text.addStretch()
        owner_layout.addWidget(self.owner_avatar)
        owner_layout.addLayout(owner_text, 1)
        info_layout.addWidget(owner_card)

        playlist_card = QFrame()
        playlist_card.setObjectName("playlistCard")
        playlist_layout = QVBoxLayout(playlist_card)
        playlist_layout.setContentsMargins(12, 12, 12, 8)
        playlist_layout.setSpacing(8)
        self.series_title = QLabel("选集")
        self.series_title.setObjectName("playlistTitle")
        self.series_title.setWordWrap(True)
        self.part_title = QLabel()
        self.part_title.setObjectName("muted")
        self.episode_list = QListWidget()
        self.episode_list.setObjectName("episodeList")
        self.episode_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.episode_list.itemClicked.connect(self._episode_clicked)
        playlist_layout.addWidget(self.series_title)
        playlist_layout.addWidget(self.part_title)
        playlist_layout.addWidget(self.episode_list, 1)
        info_layout.addWidget(playlist_card, 1)

        self.autoplay = QCheckBox("自动连播")
        self.autoplay.setChecked(settings.autoplay)
        self.autoplay.toggled.connect(self._set_autoplay)
        info_layout.addWidget(self.autoplay)
        body.addWidget(self.info_panel)
        self.root_layout.addLayout(body, 1)

        self.controls_container = QFrame(self.player_stage)
        self.controls_container.setObjectName("playerControls")
        self.controls_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        controls = QVBoxLayout(self.controls_container)
        controls.setContentsMargins(10, 4, 10, 5)
        controls.setSpacing(1)
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(0, 0, 0, 0)
        bottom_controls.setSpacing(3)
        self.previous_button = QPushButton()
        self.previous_button.setObjectName("playerButton")
        self.previous_button.setFixedSize(34, 34)
        self.previous_button.setIcon(QIcon(str(self.asset_dir / "icons" / "previous.svg")))
        self.previous_button.setIconSize(QSize(20, 20))
        self.previous_button.setToolTip("上一集")
        self.previous_button.clicked.connect(lambda: self._play_adjacent(-1))
        self.previous_button.hide()
        self.play_button = QPushButton()
        self.play_button.setObjectName("playerButton")
        self.play_button.setFixedSize(38, 34)
        self.play_icon = QIcon(str(self.asset_dir / "icons" / "play.svg"))
        self.pause_icon = QIcon(str(self.asset_dir / "icons" / "pause.svg"))
        self.play_button.setIcon(self.play_icon)
        self.play_button.setIconSize(QSize(22, 22))
        self.play_button.setToolTip("播放/暂停（Space）")
        self.play_button.clicked.connect(self._toggle_pause)
        self.next_button = QPushButton()
        self.next_button.setObjectName("playerButton")
        self.next_button.setFixedSize(34, 34)
        self.next_button.setIcon(QIcon(str(self.asset_dir / "icons" / "next.svg")))
        self.next_button.setIconSize(QSize(20, 20))
        self.next_button.setToolTip("下一集")
        self.next_button.clicked.connect(lambda: self._play_adjacent(1))
        self.next_button.hide()
        self.timeline = ChapterSlider(Qt.Orientation.Horizontal)
        self.timeline.setObjectName("playerTimeline")
        self.timeline.setRange(0, 1000)
        self.timeline.setValue(0)
        self.timeline.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.timeline.sliderReleased.connect(self._seek_from_slider)
        controls.addWidget(self.timeline)
        self.danmaku = QPushButton("弹")
        self.danmaku.setObjectName("playerToggleButton")
        self.danmaku.setCheckable(True)
        self.danmaku.setFixedSize(38, 34)
        self.danmaku.setToolTip("开启/关闭弹幕（D）")
        self.danmaku.setChecked(True)
        self.danmaku.toggled.connect(self._toggle_danmaku)
        self.subtitle = QCheckBox("字幕")
        self.subtitle.setToolTip("开启/关闭字幕（S）")
        self.subtitle.setChecked(True)
        self.subtitle.toggled.connect(self._toggle_subtitle)
        self.subtitle_track = QComboBox()
        self.subtitle_track.setMinimumWidth(92)
        self.subtitle_track.setMaximumWidth(145)
        self.subtitle_track.currentIndexChanged.connect(self._subtitle_track_changed)
        self.time_label = QLineEdit("00:00 / 00:00")
        self.time_label.setObjectName("playerTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(145)
        self.time_label.setToolTip("点击后输入 01:23:45 或 12:34，按回车跳转")
        self.time_label.returnPressed.connect(self._seek_from_time_input)
        self.speed_label = SpeedLabel()
        self.speed_label.setObjectName("speedLabel")
        self.speed_label.setToolTip("悬停滚轮每格调整 0.05×；双击恢复 1.00×")
        self.speed_label.speed_changed.connect(self._adjust_speed)
        self.speed_label.reset_requested.connect(self._reset_speed)
        self._render_speed()
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("playerToolButton")
        self.settings_button.setFixedSize(40, 34)
        self.settings_button.setToolTip("弹幕显示设置")
        self.settings_button.clicked.connect(lambda: self._show_display_settings(0))
        self.subtitle_button = QPushButton("字幕")
        self.subtitle_button.setObjectName("playerToggleButton")
        self.subtitle_button.setCheckable(True)
        self.subtitle_button.setChecked(True)
        self.subtitle_button.setToolTip("点击开关字幕，悬停选择字幕轨道")
        self.subtitle_button.clicked.connect(self._toggle_subtitle_from_button)
        self.subtitle_button.hide()
        self.chapter_button = QPushButton("章节")
        self.chapter_button.setObjectName("playerToolButton")
        self.chapter_button.setToolTip("查看章节并跳转")
        self.chapter_button.setMaximumWidth(190)
        self.chapter_button.clicked.connect(self._toggle_chapter_menu)
        self.chapter_button.hide()
        self.volume_control = QFrame()
        self.volume_control.setObjectName("volumeControl")
        volume_layout = QHBoxLayout(self.volume_control)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        self.volume_icon = QIcon(str(self.asset_dir / "icons" / "volume.svg"))
        self.mute_icon = QIcon(str(self.asset_dir / "icons" / "mute.svg"))
        self.volume_button = QPushButton()
        self.volume_button.setObjectName("playerButton")
        self.volume_button.setFixedSize(34, 34)
        self.volume_button.setIconSize(QSize(20, 20))
        self.volume_button.setToolTip("点击静音，悬停调节音量")
        self.volume_button.clicked.connect(self._toggle_mute)
        volume_layout.addWidget(self.volume_button)
        self.fullscreen_button = QPushButton()
        self.fullscreen_button.setObjectName("playerButton")
        self.fullscreen_button.setFixedSize(38, 34)
        self.fullscreen_button.setIcon(QIcon(str(self.asset_dir / "icons" / "fullscreen.svg")))
        self.fullscreen_button.setIconSize(QSize(19, 19))
        self.fullscreen_button.setToolTip("全屏（F，也可双击画面）")
        self.fullscreen_button.clicked.connect(self.fullscreen_requested)
        bottom_controls.addWidget(self.previous_button)
        bottom_controls.addWidget(self.play_button)
        bottom_controls.addWidget(self.next_button)
        bottom_controls.addWidget(self.time_label)
        bottom_controls.addWidget(self.chapter_button)
        bottom_controls.addWidget(self.danmaku)
        bottom_controls.addStretch()
        bottom_controls.addWidget(self.speed_label)
        bottom_controls.addWidget(self.subtitle_button)
        bottom_controls.addWidget(self.volume_control)
        bottom_controls.addWidget(self.settings_button)
        bottom_controls.addWidget(self.fullscreen_button)
        controls.addLayout(bottom_controls)

        self.speed_menu = QFrame(self.player_stage)
        self.speed_menu.setObjectName("playerMenu")
        self.speed_menu.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        speed_menu_layout = QVBoxLayout(self.speed_menu)
        speed_menu_layout.setContentsMargins(14, 11, 14, 12)
        speed_menu_layout.setSpacing(8)
        speed_title_row = QHBoxLayout()
        speed_title_row.addWidget(QLabel("无级调节"))
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setObjectName("speedInput")
        self.speed_input.setRange(0.0, 5.0)
        self.speed_input.setDecimals(2)
        self.speed_input.setSingleStep(0.05)
        self.speed_input.setSuffix("×")
        self.speed_input.setValue(float(self.speed.speed))
        self.speed_input.valueChanged.connect(self._speed_input_changed)
        speed_title_row.addStretch()
        speed_title_row.addWidget(self.speed_input)
        speed_menu_layout.addLayout(speed_title_row)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setObjectName("speedMenuSlider")
        self.speed_slider.setRange(0, 500)
        self.speed_slider.setSingleStep(5)
        self.speed_slider.setPageStep(25)
        self.speed_slider.setValue(round(float(self.speed.speed) * 100))
        self.speed_slider.valueChanged.connect(self._speed_slider_changed)
        speed_menu_layout.addWidget(self.speed_slider)
        self.speed_menu.hide()

        self.volume_menu = QFrame(self.player_stage)
        self.volume_menu.setObjectName("playerMenu")
        self.volume_menu.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        volume_menu_layout = QVBoxLayout(self.volume_menu)
        volume_menu_layout.setContentsMargins(10, 10, 10, 10)
        volume_menu_layout.setSpacing(5)
        self.volume_number = QLabel(str(settings.volume))
        self.volume_number.setObjectName("volumeNumber")
        self.volume_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_slider = QSlider(Qt.Orientation.Vertical)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(settings.volume)
        self.volume_slider.setFixedHeight(86)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.volume_slider.sliderReleased.connect(self._save_volume)
        volume_menu_layout.addWidget(self.volume_number)
        volume_menu_layout.addWidget(self.volume_slider, 1, Qt.AlignmentFlag.AlignHCenter)
        self.volume_menu.hide()
        self._render_volume()

        self.subtitle_menu = QFrame(self.player_stage)
        self.subtitle_menu.setObjectName("playerMenu")
        self.subtitle_menu.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        subtitle_menu_layout = QVBoxLayout(self.subtitle_menu)
        subtitle_menu_layout.setContentsMargins(14, 12, 14, 12)
        subtitle_menu_layout.setSpacing(9)
        subtitle_menu_layout.addWidget(self.subtitle)
        subtitle_track_label = QLabel("字幕轨道")
        subtitle_track_label.setObjectName("settingsCaption")
        subtitle_menu_layout.addWidget(subtitle_track_label)
        subtitle_menu_layout.addWidget(self.subtitle_track)
        self.subtitle_settings_button = QPushButton("字幕显示设置")
        self.subtitle_settings_button.setObjectName("menuAction")
        self.subtitle_settings_button.clicked.connect(lambda: self._show_display_settings(1))
        subtitle_menu_layout.addWidget(self.subtitle_settings_button)
        self.subtitle_menu.hide()

        self.chapter_menu = QListWidget(self.player_stage)
        self.chapter_menu.setObjectName("chapterMenu")
        self.chapter_menu.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.chapter_menu.itemClicked.connect(self._chapter_clicked)
        self.chapter_menu.hide()

        self.display_settings = QFrame(self.player_stage)
        self.display_settings.setObjectName("playSettings")
        self.display_settings.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        settings_layout = QVBoxLayout(self.display_settings)
        settings_layout.setContentsMargins(16, 13, 16, 14)
        settings_layout.setSpacing(9)
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.danmaku_tab_button = QPushButton("弹幕")
        self.subtitle_tab_button = QPushButton("字幕")
        for index, button in enumerate((self.danmaku_tab_button, self.subtitle_tab_button)):
            button.setObjectName("settingsTab")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, index=index: self._show_settings_tab(index))
            tabs.addWidget(button)
            button.hide()
        tabs.addStretch()
        settings_layout.addLayout(tabs)
        self.settings_stack = QStackedWidget()
        self.settings_stack.setObjectName("settingsPages")
        settings_layout.addWidget(self.settings_stack)

        self.danmaku_size = self._slider(18, 72, settings.danmaku_font_size)
        self.danmaku_opacity = self._slider(10, 100, round(settings.danmaku_opacity * 100))
        self.danmaku_speed = self._slider(4, 18, round(settings.danmaku_speed))
        self.danmaku_area = self._slider(20, 100, round(settings.danmaku_display_area * 100))
        self.danmaku_density = self._slider(20, 100, settings.danmaku_density)
        self.subtitle_size = self._slider(18, 72, settings.subtitle_font_size)
        self.subtitle_position = self._slider(65, 96, settings.subtitle_position)
        self.subtitle_background = self._slider(0, 90, round(settings.subtitle_background_opacity * 100))

        self.setting_values: dict[str, QLabel] = {}

        def setting_row(name: str, key: str, slider: QSlider) -> QWidget:
            row_widget = QWidget()
            row_widget.setObjectName("settingRow")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            name_label = QLabel(name)
            name_label.setFixedWidth(68)
            value = QLabel()
            value.setObjectName("settingValue")
            value.setFixedWidth(42)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setting_values[key] = value
            row.addWidget(name_label)
            row.addWidget(slider, 1)
            row.addWidget(value)
            slider.valueChanged.connect(self._render_display_settings)
            slider.sliderReleased.connect(self._apply_display_settings)
            return row_widget

        danmaku_page = QWidget()
        danmaku_layout = QVBoxLayout(danmaku_page)
        danmaku_layout.setContentsMargins(0, 0, 0, 0)
        danmaku_layout.setSpacing(8)
        type_title = QLabel("按类型显示")
        type_title.setObjectName("settingsCaption")
        danmaku_layout.addWidget(type_title)
        self.scroll_type = QCheckBox("滚动")
        self.top_type = QCheckBox("顶部")
        self.bottom_type = QCheckBox("底部")
        for checkbox, checked in (
            (self.scroll_type, settings.danmaku_scroll),
            (self.top_type, settings.danmaku_top),
            (self.bottom_type, settings.danmaku_bottom),
        ):
            checkbox.setChecked(checked)
            checkbox.toggled.connect(self._apply_display_settings)
        type_row = QHBoxLayout()
        type_row.addWidget(self.scroll_type)
        type_row.addWidget(self.top_type)
        type_row.addWidget(self.bottom_type)
        type_row.addStretch()
        danmaku_layout.addLayout(type_row)
        for name, key, slider in (
            ("显示区域", "danmaku_area", self.danmaku_area),
            ("不透明度", "danmaku_opacity", self.danmaku_opacity),
            ("弹幕字号", "danmaku_size", self.danmaku_size),
            ("弹幕速度", "danmaku_speed", self.danmaku_speed),
            ("弹幕密度", "danmaku_density", self.danmaku_density),
        ):
            danmaku_layout.addWidget(setting_row(name, key, slider))
        danmaku_layout.addStretch()

        subtitle_page = QWidget()
        subtitle_layout = QVBoxLayout(subtitle_page)
        subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_layout.setSpacing(9)
        subtitle_caption = QLabel("字幕显示")
        subtitle_caption.setObjectName("settingsCaption")
        subtitle_layout.addWidget(subtitle_caption)
        for name, key, slider in (
            ("字幕字号", "subtitle_size", self.subtitle_size),
            ("字幕位置", "subtitle_position", self.subtitle_position),
            ("背景深浅", "subtitle_background", self.subtitle_background),
        ):
            subtitle_layout.addWidget(setting_row(name, key, slider))
        subtitle_layout.addStretch()
        self.settings_stack.addWidget(danmaku_page)
        self.settings_stack.addWidget(subtitle_page)
        self._show_settings_tab(0)
        self.display_settings.hide()
        self._render_display_settings()
        self.overlay_timer = QTimer(self)
        self.overlay_timer.setSingleShot(True)
        self.overlay_timer.setInterval(2600)
        self.overlay_timer.timeout.connect(self._hide_player_controls)
        self.settings_hide_timer = QTimer(self)
        self.settings_hide_timer.setSingleShot(True)
        self.settings_hide_timer.setInterval(450)
        self.settings_hide_timer.timeout.connect(self.display_settings.hide)
        self.subtitle_hide_timer = QTimer(self)
        self.subtitle_hide_timer.setSingleShot(True)
        self.subtitle_hide_timer.setInterval(350)
        self.subtitle_hide_timer.timeout.connect(self.subtitle_menu.hide)
        self.speed_hide_timer = QTimer(self)
        self.speed_hide_timer.setSingleShot(True)
        self.speed_hide_timer.setInterval(350)
        self.speed_hide_timer.timeout.connect(self.speed_menu.hide)
        self.volume_hide_timer = QTimer(self)
        self.volume_hide_timer.setSingleShot(True)
        self.volume_hide_timer.setInterval(350)
        self.volume_hide_timer.timeout.connect(self.volume_menu.hide)
        self.chapter_hide_timer = QTimer(self)
        self.chapter_hide_timer.setSingleShot(True)
        self.chapter_hide_timer.setInterval(350)
        self.chapter_hide_timer.timeout.connect(self.chapter_menu.hide)
        self.player_stage.installEventFilter(self)
        self.controls_container.installEventFilter(self)
        for control in self.controls_container.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.display_settings.installEventFilter(self)
        for control in self.display_settings.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.subtitle_menu.installEventFilter(self)
        for control in self.subtitle_menu.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.speed_menu.installEventFilter(self)
        for control in self.speed_menu.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.volume_menu.installEventFilter(self)
        for control in self.volume_menu.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.chapter_menu.installEventFilter(self)
        for control in self.chapter_menu.findChildren(QWidget):
            control.setMouseTracking(True)
            control.installEventFilter(self)
        self.danmaku_bar_settings.installEventFilter(self)
        for region in (self.top_bar, self.info_panel, self.video_surface, self.danmaku_bar):
            region.installEventFilter(self)
            for control in region.findChildren(QWidget):
                control.installEventFilter(self)
        self._update_control_locations()
        QTimer.singleShot(0, self._layout_player_overlays)

    def eventFilter(self, watched, event):
        if watched is self.player_stage and event.type() == QEvent.Type.Resize:
            self._layout_player_overlays()
        in_settings = (
            watched is self.settings_button
            or watched is self.danmaku_bar_settings
            or watched is self.subtitle_settings_button
            or watched is self.display_settings
            or (isinstance(watched, QWidget) and self.display_settings.isAncestorOf(watched))
        )
        in_subtitle_menu = (
            watched is self.subtitle_button
            or watched is self.subtitle_menu
            or (isinstance(watched, QWidget) and self.subtitle_menu.isAncestorOf(watched))
        )
        in_speed_menu = (
            watched is self.speed_label
            or watched is self.speed_menu
            or (isinstance(watched, QWidget) and self.speed_menu.isAncestorOf(watched))
        )
        in_volume = (
            watched is self.volume_control
            or watched is self.volume_button
            or watched is self.volume_menu
            or watched is self.volume_slider
            or (isinstance(watched, QWidget) and self.volume_control.isAncestorOf(watched))
            or (isinstance(watched, QWidget) and self.volume_menu.isAncestorOf(watched))
        )
        in_chapter_menu = (
            watched is self.chapter_button
            or watched is self.chapter_menu
            or (isinstance(watched, QWidget) and self.chapter_menu.isAncestorOf(watched))
        )
        if in_volume and event.type() == QEvent.Type.Enter:
            self.volume_hide_timer.stop()
            self._show_volume_menu()
        elif in_volume and event.type() == QEvent.Type.Leave:
            self.volume_hide_timer.start()
        elif event.type() == QEvent.Type.MouseButtonPress and not in_volume:
            self.volume_menu.hide()
        if in_settings and event.type() == QEvent.Type.Enter:
            self.settings_hide_timer.stop()
            if watched is self.settings_button:
                self._show_display_settings(0)
            elif watched is self.danmaku_bar_settings:
                self._show_display_settings(0)
        elif in_settings and event.type() == QEvent.Type.Leave:
            self.settings_hide_timer.start()
        elif event.type() == QEvent.Type.MouseButtonPress and not in_settings:
            self.display_settings.hide()
        if in_subtitle_menu and event.type() == QEvent.Type.Enter:
            self.subtitle_hide_timer.stop()
            self._show_subtitle_menu()
        elif in_subtitle_menu and event.type() == QEvent.Type.Leave:
            self.subtitle_hide_timer.start()
        elif event.type() == QEvent.Type.MouseButtonPress and not in_subtitle_menu:
            self.subtitle_menu.hide()
        if in_speed_menu and event.type() == QEvent.Type.Enter:
            self.speed_hide_timer.stop()
            self._show_speed_menu()
        elif in_speed_menu and event.type() == QEvent.Type.Leave:
            self.speed_hide_timer.start()
        elif event.type() == QEvent.Type.MouseButtonPress and not in_speed_menu:
            self.speed_menu.hide()
        if in_chapter_menu and event.type() == QEvent.Type.Enter:
            self.chapter_hide_timer.stop()
            self._show_chapter_menu()
        elif in_chapter_menu and event.type() == QEvent.Type.Leave:
            self.chapter_hide_timer.start()
        elif event.type() == QEvent.Type.MouseButtonPress and not in_chapter_menu:
            self.chapter_menu.hide()
        if event.type() in (
            QEvent.Type.Enter,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
        ):
            self.show_player_controls()
        return super().eventFilter(watched, event)

    def _layout_player_overlays(self) -> None:
        width = self.player_stage.width()
        height = self.player_stage.height()
        if width <= 0 or height <= 0:
            return
        margin = 14 if self._fullscreen else 0
        controls_height = max(62, min(72, self.controls_container.sizeHint().height()))
        self.controls_container.setGeometry(
            margin,
            max(0, height - controls_height - margin),
            max(1, width - margin * 2),
            controls_height,
        )
        title_height = max(42, self.fullscreen_title.sizeHint().height())
        title_width = min(
            max(1, width - margin * 2),
            max(240, self.fullscreen_title.sizeHint().width() + 24),
        )
        self.fullscreen_title.setGeometry(
            margin,
            margin,
            title_width,
            title_height,
        )
        def anchored_x(anchor: QWidget, popup_width: int) -> int:
            point = anchor.mapTo(self.player_stage, QPoint(0, 0))
            centered = point.x() + anchor.width() // 2 - popup_width // 2
            return max(margin, min(width - popup_width - margin, centered))

        popup_width = min(360, max(310, width // 3))
        popup_height = min(370, max(240, self.display_settings.sizeHint().height()))
        settings_anchor = self.settings_button if self._fullscreen else self.danmaku_bar_settings
        self.display_settings.setGeometry(
            anchored_x(settings_anchor, popup_width),
            max(margin, height - controls_height - popup_height - margin * 2),
            popup_width,
            popup_height,
        )
        subtitle_width = min(270, max(220, width // 4))
        subtitle_height = min(170, max(125, self.subtitle_menu.sizeHint().height()))
        self.subtitle_menu.setGeometry(
            anchored_x(self.subtitle_button, subtitle_width),
            max(margin, height - controls_height - subtitle_height - margin * 2),
            subtitle_width,
            subtitle_height,
        )
        chapter_width = min(420, max(280, width // 3))
        chapter_height = min(300, max(120, self.chapter_menu.sizeHint().height()))
        self.chapter_menu.setGeometry(
            anchored_x(self.chapter_button, chapter_width),
            max(margin, height - controls_height - chapter_height - margin * 2),
            chapter_width,
            chapter_height,
        )
        speed_width = 235
        speed_height = 105
        self.speed_menu.setGeometry(
            anchored_x(self.speed_label, speed_width),
            max(margin, height - controls_height - speed_height - margin * 2),
            speed_width,
            speed_height,
        )
        volume_width = 58
        volume_height = 142
        self.volume_menu.setGeometry(
            anchored_x(self.volume_button, volume_width),
            max(margin, height - controls_height - volume_height - margin * 2),
            volume_width,
            volume_height,
        )
        self.controls_container.raise_()
        if self.fullscreen_title.isVisible():
            self.fullscreen_title.raise_()
        if self.display_settings.isVisible():
            self.display_settings.raise_()
        if self.subtitle_menu.isVisible():
            self.subtitle_menu.raise_()
        if self.chapter_menu.isVisible():
            self.chapter_menu.raise_()
        if self.speed_menu.isVisible():
            self.speed_menu.raise_()
        if self.volume_menu.isVisible():
            self.volume_menu.raise_()

    def _show_display_settings(self, tab: int = 0) -> None:
        self.settings_hide_timer.stop()
        self.subtitle_menu.hide()
        self.chapter_menu.hide()
        self.speed_menu.hide()
        self.volume_menu.hide()
        self._show_settings_tab(tab)
        self.display_settings.show()
        self._layout_player_overlays()
        self.display_settings.raise_()

    def _show_subtitle_menu(self) -> None:
        if not self.subtitle_button.isVisible():
            return
        self.display_settings.hide()
        self.chapter_menu.hide()
        self.speed_menu.hide()
        self.volume_menu.hide()
        self.subtitle_menu.show()
        self._layout_player_overlays()
        self.subtitle_menu.raise_()

    def _toggle_chapter_menu(self) -> None:
        if not self.chapter_button.isVisible():
            return
        if self.chapter_menu.isVisible():
            self.chapter_menu.hide()
        else:
            self._show_chapter_menu()

    def _show_chapter_menu(self) -> None:
        if not self.chapter_button.isVisible():
            return
        self.display_settings.hide()
        self.subtitle_menu.hide()
        self.speed_menu.hide()
        self.volume_menu.hide()
        self.chapter_menu.show()
        self._layout_player_overlays()
        self.chapter_menu.raise_()

    def _show_speed_menu(self) -> None:
        self.display_settings.hide()
        self.subtitle_menu.hide()
        self.chapter_menu.hide()
        self.volume_menu.hide()
        self.speed_menu.show()
        self._layout_player_overlays()
        self.speed_menu.raise_()

    def _show_volume_menu(self) -> None:
        self.display_settings.hide()
        self.subtitle_menu.hide()
        self.chapter_menu.hide()
        self.speed_menu.hide()
        self.volume_menu.show()
        self._layout_player_overlays()
        self.volume_menu.raise_()

    def _chapter_clicked(self, item: QListWidgetItem) -> None:
        start = float(item.data(Qt.ItemDataRole.UserRole) or 0)
        if self._mpv is not None:
            self._mpv.seek(start)
        self.chapter_menu.hide()

    def _update_control_locations(self) -> None:
        self.danmaku.setVisible(self._fullscreen)
        self.settings_button.setVisible(self._fullscreen)
        self.danmaku_bar.setVisible(not self._fullscreen)

    def _show_settings_tab(self, index: int) -> None:
        index = 1 if index == 1 else 0
        self.settings_stack.setCurrentIndex(index)
        self.danmaku_tab_button.setChecked(index == 0)
        self.subtitle_tab_button.setChecked(index == 1)

    @staticmethod
    def _slider(minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setMinimumWidth(130)
        return slider

    def load_video(self, video: ManagedVideo):
        if self._current_video is not None and self._current_video.video_unit_id == video.video_unit_id:
            self.status.hide()
            return
        self._save_history(force=True)
        self._current_video = video
        self._position = 0.0
        self._duration = 0.0
        self._last_saved_position = -5.0
        entry = self.history.get(video.video_unit_id)
        self._resume_position = entry.position_seconds if entry and not entry.completed else None
        self.title.setText(video.metadata.get("title", video.video_unit_id))
        self.fullscreen_title.setText(video.metadata.get("title", video.video_unit_id))
        stats = video.metadata.get("stats") or {}
        published_at = int(video.metadata.get("published_at") or 0)
        published = datetime.fromtimestamp(published_at).strftime("%Y-%m-%d %H:%M") if published_at else ""
        meta_parts = []
        if stats.get("view"):
            meta_parts.append(f"▷ {_human_count(stats.get('view'))}")
        if stats.get("danmaku"):
            meta_parts.append(f"弹 {_human_count(stats.get('danmaku'))}")
        if published:
            meta_parts.append(published)
        self.title_meta.setText("   ".join(meta_parts))
        self.title_meta.setVisible(bool(meta_parts))
        self.owner.setText(video.metadata.get("owner_name") or "未知 UP 主")
        avatar = QPixmap(str(video.avatar_path)) if video.avatar_path else QPixmap()
        if avatar.isNull():
            self.owner_avatar.setText("UP")
            self.owner_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.owner_avatar.setText("")
            self.owner_avatar.setPixmap(
                avatar.scaled(
                    48,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._populate_playlist(video)
        self.subtitle_track.blockSignals(True)
        self.subtitle_track.clear()
        subtitle_entries = video.metadata.get("subtitles") or []
        for index, entry_data in enumerate(subtitle_entries):
            name = entry_data.get("name") or entry_data.get("language") or f"字幕 {index + 1}"
            if entry_data.get("ai_generated"):
                name += "（AI）"
            self.subtitle_track.addItem(name, index)
        self.subtitle_track.blockSignals(False)
        has_subtitles = bool(subtitle_entries)
        self.subtitle_button.setVisible(has_subtitles)
        if not has_subtitles:
            self.subtitle_menu.hide()
        chapters = video.metadata.get("chapters") or []
        self.chapter_menu.clear()
        for chapter in chapters:
            start = float(chapter.get("start", 0) or 0)
            item = QListWidgetItem(str(chapter.get("title") or "未命名章节"))
            item.setData(Qt.ItemDataRole.UserRole, start)
            item.setToolTip(f"{_clock(start)} 开始")
            self.chapter_menu.addItem(item)
        has_chapters = bool(chapters)
        self.chapter_button.setVisible(has_chapters)
        self.timeline.set_chapters(chapters, float(video.metadata.get("duration", 0) or 0))
        if not has_chapters:
            self.chapter_menu.hide()
        self._update_current_chapter(0.0)
        self.danmaku_bar_status.setText("本地弹幕" if video.danmaku_path else "无弹幕")
        if video.media_path is None:
            self.status.setText("这个文件包里没有可播放的视频文件")
            return
        try:
            self._ensure_backend()
            danmaku = self._prepare_danmaku(video)
            subtitle = self._prepare_subtitle(video)
            assert self._mpv is not None
            self._mpv.load(
                video.media_path,
                danmaku,
                video.audio_path,
                subtitle,
            )
            self._mpv.set_danmaku_visible(self.danmaku.isChecked())
            self._mpv.set_subtitle_visible(self.subtitle.isChecked())
            starts_paused = self.speed.speed == 0
            self._mpv.set_paused(starts_paused)
            self._pause_changed(starts_paused)
            self.status.hide()
        except (MpvUnavailableError, OSError, ValueError) as error:
            self.status.setText(str(error))
            self.status.show()

    def set_playlist(self, videos: tuple[ManagedVideo, ...]) -> None:
        self._playlist = videos
        if self._current_video is not None:
            self._populate_playlist(self._current_video)

    def _populate_playlist(self, current: ManagedVideo) -> None:
        metadata = current.metadata
        collection = metadata.get("collection_title") or ""
        series = metadata.get("series_title") or metadata.get("title") or ""
        if collection:
            videos = tuple(
                video for video in self._playlist
                if (video.metadata.get("collection_title") or "") == collection
            )
        else:
            videos = tuple(
                video for video in self._playlist
                if (video.metadata.get("series_title") or video.metadata.get("title") or "") == series
            )
        if not videos:
            videos = (current,)
        videos = tuple(sorted(videos, key=lambda item: (int(item.metadata.get("page") or 1), item.video_unit_id)))
        self._visible_playlist = videos
        has_multiple = len(videos) > 1
        self.previous_button.setVisible(has_multiple)
        self.next_button.setVisible(has_multiple)
        self.series_title.setText(collection or series or "选集")
        self.part_title.setText(f"选集  ·  {len(videos)} 个已下载视频")
        self.episode_list.clear()
        for video in videos:
            page = int(video.metadata.get("page") or 1)
            title = video.metadata.get("part_title") or video.metadata.get("title") or video.video_unit_id
            duration = float(video.metadata.get("duration") or 0)
            suffix = f"   {_clock(duration)}" if duration > 0 else ""
            item = QListWidgetItem(f"P{page}  {title}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, video)
            self.episode_list.addItem(item)
            if video.video_unit_id == current.video_unit_id:
                item.setSelected(True)
                self.episode_list.setCurrentItem(item)
        current_index = next(
            (index for index, video in enumerate(videos) if video.video_unit_id == current.video_unit_id),
            -1,
        )
        self.previous_button.setEnabled(current_index > 0)
        self.next_button.setEnabled(0 <= current_index < len(videos) - 1)

    def _episode_clicked(self, item: QListWidgetItem) -> None:
        video = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(video, ManagedVideo) and (
            self._current_video is None or video.video_unit_id != self._current_video.video_unit_id
        ):
            self.video_requested.emit(video)

    def _play_adjacent(self, offset: int) -> bool:
        if self._current_video is None or len(self._visible_playlist) < 2:
            return False
        current_index = next(
            (
                index for index, video in enumerate(self._visible_playlist)
                if video.video_unit_id == self._current_video.video_unit_id
            ),
            -1,
        )
        target_index = current_index + offset
        if current_index < 0 or not 0 <= target_index < len(self._visible_playlist):
            return False
        self.video_requested.emit(self._visible_playlist[target_index])
        return True

    def shutdown(self) -> None:
        self._save_history(force=True)
        if self._mpv is not None:
            self._mpv.shutdown()
            self._mpv = None

    def pause_for_navigation(self) -> None:
        self._save_history(force=True)
        if self._mpv is not None:
            self._mpv.set_paused(True)
            self._pause_changed(True)

    def set_fullscreen_mode(self, active: bool) -> None:
        self._fullscreen = active
        self.top_bar.setVisible(not active)
        self.info_panel.setVisible(not active)
        self.display_settings.hide()
        self.subtitle_menu.hide()
        self.chapter_menu.hide()
        self.speed_menu.hide()
        self.volume_menu.hide()
        self._update_control_locations()
        for widget in (self.video_surface, self.controls_container):
            widget.setProperty("fullscreen", active)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if active:
            self.root_layout.setContentsMargins(0, 0, 0, 0)
        else:
            self.player_stage.unsetCursor()
            self.root_layout.setContentsMargins(26, 18, 26, 22)
        self.fullscreen_title.setVisible(active)
        self.show_player_controls()
        self._layout_player_overlays()
        refresh_video = getattr(self._mpv, "refresh_video", None)
        if refresh_video is not None:
            QTimer.singleShot(0, refresh_video)

    def show_player_controls(self) -> None:
        self.player_stage.unsetCursor()
        self.controls_container.show()
        self.fullscreen_title.setVisible(self._fullscreen)
        self._layout_player_overlays()
        if self._paused:
            self.overlay_timer.stop()
        else:
            self.overlay_timer.start()

    def _hide_player_controls(self) -> None:
        if any(
            menu.isVisible()
            for menu in (
                self.display_settings,
                self.subtitle_menu,
                self.chapter_menu,
                self.speed_menu,
                self.volume_menu,
            )
        ):
            self.overlay_timer.start()
            return
        if not self._paused:
            self.controls_container.hide()
            self.fullscreen_title.hide()
            self.display_settings.hide()
            self.subtitle_menu.hide()
            self.chapter_menu.hide()
            self.speed_menu.hide()
            self.volume_menu.hide()
            if self._fullscreen:
                self.player_stage.setCursor(Qt.CursorShape.BlankCursor)

    def _ensure_backend(self) -> None:
        if self._mpv is not None:
            return
        self._mpv = MpvBackend(int(self.video_surface.winId()), self.tools_dir, self)
        self._mpv.position_changed.connect(self._position_changed)
        self._mpv.duration_changed.connect(self._duration_changed)
        self._mpv.pause_changed.connect(self._pause_changed)
        self._mpv.ended.connect(self._playback_ended)
        self.backend = self._mpv
        self.speed.backend = self._mpv
        self.speed.set(self.settings.playback_speed)
        self._mpv.set_volume(self.settings.volume)

    def _prepare_danmaku(self, video: ManagedVideo) -> Path | None:
        if video.danmaku_path is None:
            return None
        cache = self.cache_dir / "danmaku"
        cache.mkdir(parents=True, exist_ok=True)
        ass_path = cache / f"{video.video_unit_id}.ass"
        xml_text = video.danmaku_path.read_text(encoding="utf-8")
        ass_path.write_text(
            render_ass(
                parse_bilibili_xml(xml_text),
                DanmakuSettings(
                    font_size=self.settings.danmaku_font_size,
                    opacity=self.settings.danmaku_opacity,
                    display_area=self.settings.danmaku_display_area,
                    scroll_duration=self.settings.danmaku_speed,
                    density=self.settings.danmaku_density,
                    show_scroll=self.settings.danmaku_scroll,
                    show_top=self.settings.danmaku_top,
                    show_bottom=self.settings.danmaku_bottom,
                ),
            ),
            encoding="utf-8-sig",
        )
        return ass_path

    def _prepare_subtitle(self, video: ManagedVideo) -> Path | None:
        entries = video.metadata.get("subtitles") or []
        if not entries:
            return None
        index = min(max(0, self.subtitle_track.currentIndex()), len(entries) - 1)
        source = video.package_dir / entries[index].get("file", "")
        if not source.is_file():
            return None
        cache = self.cache_dir / "subtitles"
        cache.mkdir(parents=True, exist_ok=True)
        ass_path = cache / f"{video.video_unit_id}-{index}.ass"
        ass_path.write_text(
            render_bilibili_subtitle(
                source,
                SubtitleSettings(
                    font_size=self.settings.subtitle_font_size,
                    position=self.settings.subtitle_position,
                    background_opacity=self.settings.subtitle_background_opacity,
                ),
            ),
            encoding="utf-8-sig",
        )
        return ass_path

    def toggle_pause(self) -> None:
        self.display_settings.hide()
        if self._mpv is None:
            return
        if self.speed.speed == 0 and self._paused:
            self.settings.playback_speed = self.speed.reset()
            self.settings_store.save(self.settings)
            self._render_speed()
        self._mpv.set_paused(not self._paused)
        self._pause_changed(not self._paused)

    def _toggle_pause(self) -> None:
        self.toggle_pause()

    def toggle_danmaku(self) -> None:
        self.danmaku.setChecked(not self.danmaku.isChecked())

    def toggle_subtitle(self) -> None:
        if self.subtitle_button.isVisible():
            self.subtitle.setChecked(not self.subtitle.isChecked())

    def seek_relative(self, seconds: float) -> None:
        if self._mpv is not None and self._duration > 0:
            self._mpv.seek(min(self._duration, max(0.0, self._position + seconds)))

    def _toggle_danmaku(self, visible: bool) -> None:
        self.danmaku_bar_toggle.blockSignals(True)
        self.danmaku_bar_toggle.setChecked(visible)
        self.danmaku_bar_toggle.blockSignals(False)
        if self._mpv is not None:
            self._mpv.set_danmaku_visible(visible)

    def _toggle_danmaku_from_bar(self, visible: bool) -> None:
        self.danmaku.blockSignals(True)
        self.danmaku.setChecked(visible)
        self.danmaku.blockSignals(False)
        self._toggle_danmaku(visible)

    def _toggle_subtitle(self, visible: bool) -> None:
        self.subtitle_button.blockSignals(True)
        self.subtitle_button.setChecked(visible)
        self.subtitle_button.blockSignals(False)
        if self._mpv is not None:
            self._mpv.set_subtitle_visible(visible)

    def _toggle_subtitle_from_button(self) -> None:
        self.subtitle.setChecked(not self.subtitle.isChecked())

    def _subtitle_track_changed(self, _index: int) -> None:
        if self._mpv is not None and self._current_video is not None:
            self._mpv.reload_subtitle(self._prepare_subtitle(self._current_video))
            self._mpv.set_subtitle_visible(self.subtitle.isChecked())

    def _playback_ended(self) -> None:
        if self._duration > 0:
            self._position = self._duration
            self._save_history(force=True)
        if self.settings.autoplay:
            self._play_adjacent(1)

    def _position_changed(self, seconds: float) -> None:
        self._position = seconds
        if self._duration > 0 and not self._seeking:
            self.timeline.setValue(round(seconds / self._duration * 1000))
        if not self.time_label.hasFocus():
            self.time_label.setText(f"{_clock(seconds)} / {_clock(self._duration)}")
        self._update_current_chapter(seconds)
        self._save_history()

    def _duration_changed(self, seconds: float) -> None:
        self._duration = seconds
        chapters = (self._current_video.metadata.get("chapters") or []) if self._current_video else []
        self.timeline.set_chapters(chapters, seconds)
        if not self.time_label.hasFocus():
            self.time_label.setText(f"{_clock(self._position)} / {_clock(seconds)}")
        if self._resume_position is not None and self._mpv is not None:
            resume_position = min(self._resume_position, max(0.0, seconds - 1))
            self._resume_position = None
            self._mpv.seek(resume_position)

    def _update_current_chapter(self, seconds: float) -> None:
        if self._current_video is None:
            return
        chapters = self._current_video.metadata.get("chapters") or []
        current_index = next(
            (
                index for index in range(len(chapters) - 1, -1, -1)
                if float(chapters[index].get("start", 0) or 0) <= seconds
            ),
            -1,
        )
        if current_index >= 0:
            current = chapters[current_index]
            title = str(current.get("title") or "章节")
            compact_title = title if len(title) <= 12 else title[:11] + "…"
            self.chapter_button.setText(f"章节 · {compact_title}")
            self.chapter_button.setToolTip(title)
            if self.chapter_menu.currentRow() != current_index:
                self.chapter_menu.setCurrentRow(current_index)
        else:
            self.chapter_button.setText("章节")

    def _pause_changed(self, paused: bool) -> None:
        self._paused = paused
        self.play_button.setIcon(self.play_icon if paused else self.pause_icon)
        if paused:
            self.overlay_timer.stop()
            self.show_player_controls()
        else:
            self.overlay_timer.start()

    def _seek_from_slider(self) -> None:
        self._seeking = False
        if self._mpv is not None and self._duration > 0:
            self._mpv.seek(self.timeline.value() / 1000 * self._duration)

    def _seek_from_time_input(self) -> None:
        seconds = _parse_timecode(self.time_label.text())
        if seconds is not None and self._mpv is not None and self._duration > 0:
            self._mpv.seek(min(self._duration, seconds))
        self.time_label.clearFocus()
        self.time_label.setText(f"{_clock(self._position)} / {_clock(self._duration)}")

    def _save_history(self, force: bool = False) -> None:
        if self._current_video is None or self._duration <= 0:
            return
        if force or self._position - self._last_saved_position >= 5 or self._position / self._duration >= 0.99:
            self.history.record_progress(
                self._current_video.video_unit_id,
                self._position,
                self._duration,
            )
            self._last_saved_position = self._position

    def _adjust_speed(self, steps: float):
        self._set_speed_value(self.speed.adjust_wheel(int(steps)))

    def _reset_speed(self):
        self._set_speed_value(self.speed.reset())

    def _speed_input_changed(self, value: float) -> None:
        self._set_speed_value(value)

    def _speed_slider_changed(self, value: int) -> None:
        self._set_speed_value(value / 100)

    def _set_speed_value(self, value: float) -> None:
        self.settings.playback_speed = self.speed.set(value)
        self.settings_store.save(self.settings)
        self._render_speed()

    def _render_speed(self):
        speed = float(self.speed.speed)
        self.speed_label.setText("无级倍速" if speed == 1.0 else f"{speed:.2f}×")
        if hasattr(self, "speed_input"):
            self.speed_input.blockSignals(True)
            self.speed_input.setValue(speed)
            self.speed_input.blockSignals(False)
        if hasattr(self, "speed_slider"):
            self.speed_slider.blockSignals(True)
            self.speed_slider.setValue(round(speed * 100))
            self.speed_slider.blockSignals(False)

    def _volume_changed(self, volume: int) -> None:
        self.settings.volume = volume
        self.backend.set_volume(volume)
        self._render_volume()

    def _save_volume(self) -> None:
        self.settings_store.save(self.settings)

    def _toggle_mute(self) -> None:
        if self.volume_slider.value() == 0:
            self.volume_slider.setValue(max(1, getattr(self, "_volume_before_mute", 100)))
        else:
            self._volume_before_mute = self.volume_slider.value()
            self.volume_slider.setValue(0)
        self._save_volume()

    def _render_volume(self) -> None:
        muted = self.volume_slider.value() == 0
        self.volume_number.setText(str(self.volume_slider.value()))
        self.volume_button.setIcon(self.mute_icon if muted else self.volume_icon)
        self.volume_button.setToolTip(
            "点击恢复音量" if muted else f"音量 {self.volume_slider.value()}% · 点击静音"
        )

    def _set_autoplay(self, enabled: bool) -> None:
        self.settings.autoplay = enabled
        self.settings_store.save(self.settings)

    def _render_display_settings(self) -> None:
        values = {
            "danmaku_size": f"{self.danmaku_size.value()}px",
            "danmaku_opacity": f"{self.danmaku_opacity.value()}%",
            "danmaku_speed": f"{self.danmaku_speed.value()}s",
            "danmaku_area": f"{self.danmaku_area.value()}%",
            "danmaku_density": f"{self.danmaku_density.value()}%",
            "subtitle_size": f"{self.subtitle_size.value()}px",
            "subtitle_position": f"{self.subtitle_position.value()}%",
            "subtitle_background": f"{self.subtitle_background.value()}%",
        }
        for key, value in values.items():
            self.setting_values[key].setText(value)

    def _apply_display_settings(self, _checked: bool | None = None) -> None:
        self.settings.danmaku_font_size = self.danmaku_size.value()
        self.settings.danmaku_opacity = self.danmaku_opacity.value() / 100
        self.settings.danmaku_speed = float(self.danmaku_speed.value())
        self.settings.danmaku_display_area = self.danmaku_area.value() / 100
        self.settings.danmaku_density = self.danmaku_density.value()
        self.settings.danmaku_scroll = self.scroll_type.isChecked()
        self.settings.danmaku_top = self.top_type.isChecked()
        self.settings.danmaku_bottom = self.bottom_type.isChecked()
        self.settings.subtitle_font_size = self.subtitle_size.value()
        self.settings.subtitle_position = self.subtitle_position.value()
        self.settings.subtitle_background_opacity = self.subtitle_background.value() / 100
        self.settings_store.save(self.settings)
        if self._mpv is not None and self._current_video is not None:
            self._mpv.reload_danmaku(self._prepare_danmaku(self._current_video))
            self._mpv.reload_subtitle(self._prepare_subtitle(self._current_video))
            self._mpv.set_danmaku_visible(self.danmaku.isChecked())
            self._mpv.set_subtitle_visible(self.subtitle.isChecked())


class MainWindow(QMainWindow):
    def __init__(
        self,
        scan: LibraryScan,
        history: HistoryStore,
        settings: AppSettings,
        settings_store: SettingsStore,
        tools_dir: Path,
        cache_dir: Path,
        app_root: Path,
        data_dir: Path,
        library: ManagedLibrary,
    ):
        super().__init__()
        self.setWindowTitle("Offline Bili")
        self.icon_path = app_root / "assets" / "offline-bili.png"
        if self.icon_path.is_file():
            self.setWindowIcon(QIcon(str(self.icon_path)))
        self.resize(1320, 820)
        self.setMinimumSize(1120, 680)
        self.settings = settings
        self.settings_store = settings_store
        self.app_root = app_root
        self.data_dir = data_dir
        self._parse_thread: ParseLinksThread | None = None
        self._download_thread: DownloadThread | None = None
        self.library = library
        self.history = history
        self._scan = scan
        self.job_store = DownloadJobStore(self.data_dir / "download_jobs.json")
        self._fullscreen_player = False

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(20, 26, 20, 22)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_icon = QLabel()
        brand_icon.setObjectName("brandIcon")
        brand_icon.setFixedSize(46, 46)
        if self.icon_path.is_file():
            brand_icon.setPixmap(
                QPixmap(str(self.icon_path)).scaled(
                    46,
                    46,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        brand = QLabel("OFFLINE\nBILI")
        brand.setObjectName("brand")
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        self.library_button = QPushButton("▦  媒体库")
        self.download_nav = QPushButton("↓  下载视频")
        self.history_button = QPushButton("◴  历史记录")
        self.nav_buttons = (self.library_button, self.download_nav, self.history_button)
        for button in self.nav_buttons:
            button.setObjectName("navButton")
            button.setCheckable(True)
        self.library_button.setChecked(True)
        side_layout.addLayout(brand_row)
        side_layout.addSpacing(34)
        side_layout.addWidget(self.library_button)
        side_layout.addWidget(self.history_button)
        side_layout.addWidget(self.download_nav)
        side_layout.addStretch()

        self.pages = QStackedWidget()
        self.library_page = LibraryPage(scan, history)
        self.download_page = DownloadPage(self.job_store)
        self.history_page = HistoryPage(history, scan)
        self.player_page = PlayerPage(settings, settings_store, tools_dir, cache_dir, history)
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.download_page)
        self.pages.addWidget(self.history_page)
        self.pages.addWidget(self.player_page)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.account_bar = QFrame()
        self.account_bar.setObjectName("accountBar")
        account_layout = QHBoxLayout(self.account_bar)
        account_layout.setContentsMargins(16, 7, 24, 4)
        account_layout.addStretch()
        self.account_button = QPushButton()
        self.account_button.setObjectName("accountButton")
        self.account_button.clicked.connect(self._account_clicked)
        account_layout.addWidget(self.account_button)
        content_layout.addWidget(self.account_bar)
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(content, 1)

        self.library_button.clicked.connect(lambda: self._select_page(0, self.library_button))
        self.download_nav.clicked.connect(lambda: self._select_page(1, self.download_nav))
        self.history_button.clicked.connect(self._show_history)
        self.library_page.import_requested.connect(lambda: self._select_page(1, self.download_nav))
        self.library_page.play_requested.connect(self._show_player)
        self.library_page.delete_requested.connect(self._delete_video)
        self.history_page.play_requested.connect(self._show_player)
        self.history_page.delete_requested.connect(self._delete_history_entry)
        self.download_page.parse_requested.connect(lambda links: self._start_parse(self.download_page, links))
        self.download_page.download_requested.connect(self._queue_downloads)
        self.download_page.retry_requested.connect(self._run_jobs)
        self.download_page.remove_jobs_requested.connect(self._remove_jobs)
        self.download_page.cancel_active_requested.connect(self._cancel_download)
        self.player_page.back_requested.connect(lambda: self._select_page(0, self.library_button))
        self.player_page.fullscreen_requested.connect(self._toggle_fullscreen_player)
        self.player_page.video_requested.connect(self._show_player)
        self._player_shortcuts: list[QShortcut] = []
        self._add_player_shortcut("Space", self.player_page.toggle_pause)
        self._add_player_shortcut("F", self._toggle_fullscreen_player)
        self._add_player_shortcut("D", self.player_page.toggle_danmaku)
        self._add_player_shortcut("S", self.player_page.toggle_subtitle)
        self._add_player_shortcut("Left", lambda: self.player_page.seek_relative(-5))
        self._add_player_shortcut("Right", lambda: self.player_page.seek_relative(5))
        escape = QShortcut(QKeySequence("Escape"), self)
        escape.setContext(Qt.ShortcutContext.WindowShortcut)
        escape.activated.connect(self._exit_fullscreen_player)
        self._player_shortcuts.append(escape)
        self._refresh_account_button()

    def _add_player_shortcut(self, sequence: str, action) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(lambda action=action: self._run_player_shortcut(action))
        self._player_shortcuts.append(shortcut)

    def _run_player_shortcut(self, action) -> None:
        if self.pages.currentWidget() is self.player_page:
            action()
            self.player_page.show_player_controls()

    def _select_page(self, index: int, selected: QPushButton):
        if self.pages.currentWidget() is self.player_page and index != 3:
            self.player_page.pause_for_navigation()
        if self._fullscreen_player and index != 3:
            self._exit_fullscreen_player()
        self.pages.setCurrentIndex(index)
        for button in self.nav_buttons:
            button.setChecked(button is selected)

    def _show_history(self) -> None:
        old_page = self.history_page
        new_page = HistoryPage(self.history, self._scan)
        new_page.play_requested.connect(self._show_player)
        new_page.delete_requested.connect(self._delete_history_entry)
        self.pages.removeWidget(old_page)
        self.pages.insertWidget(2, new_page)
        self.history_page = new_page
        old_page.deleteLater()
        self._select_page(2, self.history_button)

    def _account_clicked(self) -> None:
        menu = QMessageBox(self)
        menu.setWindowTitle("B 站账号")
        profile = load_profile(self.data_dir)
        logged_in = has_login(self.data_dir)
        menu.setText(
            f"已登录：{profile.get('username') or 'B 站账号'}"
            if logged_in else "尚未登录 B 站账号"
        )
        relogin = menu.addButton("重新扫码登录" if logged_in else "扫码登录", QMessageBox.ButtonRole.AcceptRole)
        migrate = menu.addButton("迁移旧版本数据", QMessageBox.ButtonRole.ActionRole)
        menu.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        menu.exec()
        if menu.clickedButton() is relogin:
            self._show_login()
        elif menu.clickedButton() is migrate:
            self._import_legacy()

    def _show_login(self) -> None:
        try:
            adapter = Bili23Adapter(self.app_root, self.data_dir / "bili23")
        except OSError as error:
            QMessageBox.warning(self, "无法登录", str(error))
            return
        dialog = LoginDialog(adapter, self)
        dialog.login_succeeded.connect(lambda _profile: self._refresh_account_button())
        dialog.exec()
        self._refresh_account_button()

    def _refresh_account_button(self) -> None:
        logged_in = has_login(self.data_dir)
        profile = load_profile(self.data_dir)
        self.account_button.setText(profile.get("username", "已登录") if logged_in else "○  登录 B 站")
        image = avatar_path(self.data_dir)
        self.account_button.setIcon(QIcon(str(image)) if logged_in and image.is_file() else QIcon())
        self.account_button.setIconSize(QSize(28, 28))

    def _import_legacy(self) -> None:
        old_root = QFileDialog.getExistingDirectory(self, "选择旧版本程序文件夹", str(self.app_root.parent))
        if not old_root:
            return
        try:
            import_legacy_data(Path(old_root), self.data_dir)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "迁移失败", str(error))
            return
        self._refresh_account_button()
        QMessageBox.information(self, "迁移完成", "旧版本登录信息已迁移；此入口会在正式版移除。")

    def _start_parse(self, page: DownloadPage, links: tuple[str, ...]) -> None:
        if self._parse_thread is not None and self._parse_thread.isRunning():
            return
        try:
            adapter = Bili23Adapter(self.app_root, self.data_dir / "bili23")
        except OSError as error:
            page.show_error(str(error))
            return
        page.set_parsing(True)
        thread = ParseLinksThread(adapter, links, page)
        self._parse_thread = thread
        thread.succeeded.connect(page.show_results)
        thread.failed.connect(page.show_error)
        thread.finished.connect(lambda: setattr(self, "_parse_thread", None))
        thread.start()

    def _queue_downloads(self, selected: tuple, quality_id: int) -> None:
        requests = tuple(
            DownloadRequest(preview=preview, part=part, quality_id=quality_id)
            for preview, part in selected
        )
        jobs = self.job_store.add(requests)
        self.download_page.reload_jobs()
        self._run_jobs(jobs)

    def _run_jobs(self, jobs: tuple[DownloadJob, ...]) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        adapter = Bili23Adapter(self.app_root, self.data_dir / "bili23")
        coordinator = DownloadCoordinator(
            adapter,
            self.data_dir / "staging",
            self.library.library_dir,
            self.library.integrity_key,
        )
        runnable = tuple((job.job_id, job.request) for job in jobs if job.status in {"pending", "failed"})
        if not runnable:
            return
        thread = DownloadThread(coordinator, runnable, self)
        self._download_thread = thread
        thread.progress.connect(self.download_page.set_downloading)
        thread.job_changed.connect(self._job_changed)
        thread.failed.connect(self.download_page.show_download_error)
        thread.succeeded.connect(self._download_finished)
        thread.finished.connect(lambda: setattr(self, "_download_thread", None))
        thread.start()

    def _job_changed(self, job_id: str, status: str, error: str) -> None:
        self.job_store.set_status(job_id, status, error)
        self.download_page.reload_jobs()
        self.download_nav.setText("↓  下载视频 · 下载中" if status == "running" else "↓  下载视频")

    def _download_finished(self, paths: tuple[Path, ...]) -> None:
        completed = {job.job_id for job in self.job_store.list_jobs() if job.status == "completed"}
        self.job_store.remove(completed)
        self.download_page.download_finished(len(paths))
        self._replace_library_page(self.library.scan())

    def _remove_jobs(self, job_ids: tuple[str, ...]) -> None:
        running = self._download_thread is not None and self._download_thread.isRunning()
        if running:
            QMessageBox.information(self, "下载进行中", "请先取消当前下载，再移除任务。")
            return
        self.job_store.remove(set(job_ids))
        self.download_page.reload_jobs()

    def _cancel_download(self) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            self._download_thread.cancel()
            self.download_nav.setText("↓  下载视频")

    def _replace_library_page(self, scan: LibraryScan) -> None:
        self._scan = scan
        self.player_page.set_playlist(scan.videos)
        old_page = self.library_page
        was_library = self.pages.currentWidget() is old_page
        new_page = LibraryPage(scan, self.history)
        new_page.import_requested.connect(lambda: self._select_page(1, self.download_nav))
        new_page.play_requested.connect(self._show_player)
        new_page.delete_requested.connect(self._delete_video)
        self.pages.removeWidget(old_page)
        self.pages.insertWidget(0, new_page)
        self.library_page = new_page
        old_page.deleteLater()
        if was_library:
            self.pages.setCurrentWidget(new_page)

    def _show_player(self, video: ManagedVideo):
        self.player_page.set_playlist(self._scan.videos)
        self.player_page.load_video(video)
        self._select_page(3, self.library_button)
        for button in self.nav_buttons:
            button.setChecked(False)

    def _delete_history_entry(self, video: ManagedVideo) -> None:
        self.history.delete(video.video_unit_id)
        self._show_history()

    def _delete_video(self, video: ManagedVideo) -> None:
        answer = QMessageBox.question(
            self, "删除离线视频", f"确定删除《{video.metadata.get('title', video.video_unit_id)}》的整个离线包吗？"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            video.package_dir.resolve().relative_to(self.library.library_dir.resolve())
            shutil.rmtree(video.package_dir)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "删除失败", str(error))
            return
        self._replace_library_page(self.library.scan())

    def _toggle_fullscreen_player(self) -> None:
        if self._fullscreen_player:
            self._exit_fullscreen_player()
            return
        if self.pages.currentWidget() is not self.player_page:
            return
        self._fullscreen_player = True
        self._was_maximized = self.isMaximized()
        self.sidebar.hide()
        self.account_bar.hide()
        self.player_page.set_fullscreen_mode(True)
        self.showFullScreen()

    def _exit_fullscreen_player(self) -> None:
        if not self._fullscreen_player:
            return
        self._fullscreen_player = False
        self.sidebar.show()
        self.account_bar.show()
        self.player_page.set_fullscreen_mode(False)
        self.showMaximized() if getattr(self, "_was_maximized", False) else self.showNormal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._fullscreen_player:
            self._exit_fullscreen_player()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        active_parse = self._parse_thread is not None and self._parse_thread.isRunning()
        active_download = self._download_thread is not None and self._download_thread.isRunning()
        if active_parse or active_download:
            QMessageBox.information(self, "任务仍在进行", "请等待当前解析或下载完成后再关闭程序。")
            event.ignore()
            return
        self.player_page.shutdown()
        self.settings_store.save(self.settings)
        super().closeEvent(event)


def apply_theme(widget: QWidget) -> None:
    widget.setFont(QFont("Microsoft YaHei UI", 10))
    widget.setStyleSheet(
        f"""
        QWidget {{ color: {DARK}; background: white; }}
        QLabel {{ background: transparent; }}
        #sidebar {{ background: #f7f8fa; border-right: 1px solid #e3e5e7; }}
        #brand {{ color: {PINK}; font-size: 21px; font-weight: 800; letter-spacing: 1px; }}
        #muted {{ color: {MUTED}; }}
        #pageTitle {{ font-size: 27px; font-weight: 700; }}
        #sectionTitle {{ font-size: 16px; font-weight: 700; }}
        #playerTitle {{ font-size: 20px; font-weight: 500; }}
        #playerMeta {{ color: {MUTED}; font-size: 12px; }}
        #dialogTitle, #emptyTitle {{ font-size: 20px; font-weight: 700; }}
        #emptyIcon {{ color: {PINK}; font-size: 56px; font-weight: 700; }}
        QPushButton {{ border: none; border-radius: 8px; padding: 10px 15px; }}
        QPushButton:hover {{ background: #f1f2f3; }}
        QPushButton#navButton {{ text-align: left; padding: 12px 14px; font-size: 15px; }}
        QPushButton#navButton:checked {{ color: {PINK}; background: #ffeef3; font-weight: 700; }}
        QPushButton#primary {{ color: white; background: {PINK}; font-weight: 700; }}
        QPushButton#primary:hover {{ background: #f45a88; }}
        QPushButton#quiet {{ background: {SURFACE}; }}
        #accountBar {{ border-bottom: 1px solid #f1f2f3; }}
        QPushButton#accountButton {{ padding: 5px 10px; background: transparent; font-weight: 600; }}
        #videoCard {{ border: none; border-radius: 9px; background: white; }}
        #videoCard:hover {{ background: #f7f8fa; }}
        #cardTitle {{ font-size: 14px; font-weight: 600; }}
        #cardOverlay {{ background: transparent; }}
        #cardMeta, #playerTime, #settingValue {{ color: {MUTED}; font-size: 12px; }}
        #thumbnailTime {{ color: white; background: rgba(0, 0, 0, 125); border-radius: 4px; padding: 2px 5px; }}
        QPushButton#cardDelete {{ color: white; background: rgba(0, 0, 0, 125); border-radius: 11px; padding: 0; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }}
        QPushButton#cardDelete:hover {{ background: #e34b67; }}
        QProgressBar#watchProgress {{ border: none; background: #e5e7eb; border-radius: 2px; }}
        QProgressBar#watchProgress::chunk {{ background: {PINK}; border-radius: 2px; }}
        QProgressBar#downloadProgress {{ border: none; background: #e5e7eb; border-radius: 3px; min-height: 7px; max-height: 7px; }}
        QProgressBar#downloadProgress::chunk {{ background: {PINK}; border-radius: 3px; }}
        #downloadNotice {{ color: #178b55; background: #eaf8f1; border-radius: 7px; padding: 8px 12px; }}
        #downloadPreview {{ background: #f7f8fa; border: 1px solid #e3e5e7; border-radius: 10px; }}
        #previewCover {{ background: #18191c; border-radius: 8px; }}
        #previewTitle {{ font-size: 19px; font-weight: 700; }}
        #previewOwner {{ font-size: 14px; font-weight: 600; }}
        #playerStage {{ background: #0f0f11; border-radius: 2px; }}
        #videoSurface {{ background: #0f0f11; border-radius: 2px; }}
        #videoSurface[fullscreen="true"] {{ border-radius: 0; margin: 0; }}
        #fullscreenTitle {{ color: white; background: transparent; padding: 12px 18px; font-size: 18px; font-weight: 500; }}
        #playerControls {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0, 0, 0, 0), stop:0.42 rgba(0, 0, 0, 70), stop:1 rgba(0, 0, 0, 225)); border-radius: 0; }}
        #playerControls[fullscreen="true"] {{ border-radius: 0; }}
        #volumeControl {{ background: transparent; }}
        #playerControls QLabel, #playerControls QCheckBox {{ color: white; background: transparent; }}
        #playerControls QComboBox {{ color: white; background: rgba(255, 255, 255, 28); border: none; border-radius: 5px; padding: 4px 7px; }}
        #danmakuBar {{ background: white; border: 1px solid #e3e5e7; border-top: none; min-height: 40px; max-height: 40px; }}
        QPushButton#danmakuBarButton {{ color: #61666d; background: transparent; padding: 6px 10px; }}
        QPushButton#danmakuBarButton:hover {{ color: {PINK}; background: #fff1f5; }}
        #playerInfo {{ background: white; }}
        #ownerCard {{ background: white; }}
        #ownerName {{ color: {PINK}; font-size: 14px; font-weight: 600; }}
        #ownerAvatar {{ color: white; background: {PINK}; border-radius: 24px; font-weight: 700; }}
        #danmakuHeader {{ background: {SURFACE}; border-radius: 7px; font-size: 14px; }}
        #playlistCard {{ background: {SURFACE}; border-radius: 8px; }}
        #playlistTitle {{ font-size: 16px; font-weight: 600; }}
        QListWidget#episodeList {{ border: none; border-radius: 0; padding: 0; background: transparent; outline: none; }}
        QListWidget#episodeList::item {{ min-height: 34px; padding: 2px 8px; border-radius: 5px; }}
        QListWidget#episodeList::item:hover {{ background: #eef0f2; }}
        QListWidget#episodeList::item:selected {{ color: #00aeec; background: white; }}
        #playSettings {{ background: rgba(30, 30, 32, 248); border: none; border-radius: 4px; }}
        #playerMenu {{ background: rgba(30, 30, 32, 248); border: none; border-radius: 4px; }}
        #playerMenu QLabel, #playerMenu QCheckBox {{ color: #f1f1f1; background: transparent; }}
        #playerMenu QComboBox {{ color: #f1f1f1; background: rgba(255, 255, 255, 28); border: none; border-radius: 5px; padding: 6px 8px; }}
        QPushButton#menuAction {{ color: #f1f1f1; background: rgba(255, 255, 255, 20); text-align: left; padding: 7px 9px; }}
        QPushButton#menuAction:hover {{ color: #00aeec; background: rgba(255, 255, 255, 34); }}
        QListWidget#chapterMenu {{ color: #f1f1f1; background: rgba(30, 30, 32, 248); border: none; border-radius: 4px; padding: 7px; outline: none; }}
        QListWidget#chapterMenu::item {{ min-height: 32px; padding: 3px 8px; border-radius: 4px; }}
        QListWidget#chapterMenu::item:hover {{ color: white; background: rgba(255, 255, 255, 24); }}
        QListWidget#chapterMenu::item:selected {{ color: #00aeec; background: rgba(0, 174, 236, 24); }}
        #playSettings QWidget, #settingsPages, #settingRow {{ background: transparent; }}
        #playSettings QLabel, #playSettings QCheckBox {{ color: #f1f1f1; background: transparent; }}
        #settingsCaption {{ font-size: 13px; font-weight: 600; }}
        QPushButton#settingsTab {{ color: #c7c9cc; background: transparent; border-radius: 4px; padding: 4px 12px; }}
        QPushButton#settingsTab:checked {{ color: white; background: rgba(255, 255, 255, 30); font-weight: 600; }}
        #videoStatus {{ color: #9da0a8; background: transparent; font-size: 15px; }}
        #speedLabel {{ color: white; padding: 6px 10px; border-radius: 0; font-weight: 600; }}
        #speedLabel:hover {{ color: white; background: transparent; }}
        QPushButton#playerButton, QPushButton#playerToolButton, QPushButton#playerToggleButton {{ color: white; background: transparent; padding: 5px 8px; border-radius: 0; }}
        QPushButton#playerButton:hover, QPushButton#playerToolButton:hover, QPushButton#playerToggleButton:hover {{ color: white; background: transparent; }}
        QPushButton#playerToggleButton:!checked {{ color: #8d8f92; }}
        QPushButton#playerToggleButton:checked {{ color: white; }}
        QLineEdit#playerTime {{ color: white; background: transparent; border: none; padding: 4px; }}
        QLineEdit#playerTime:focus {{ background: rgba(255, 255, 255, 24); }}
        QDoubleSpinBox#speedInput {{ color: white; background: rgba(255, 255, 255, 20); border: 1px solid #57585a; border-radius: 3px; padding: 3px 5px; min-width: 66px; }}
        #volumeNumber {{ color: white; font-size: 12px; }}
        QPlainTextEdit, QListWidget {{ border: 1px solid #e3e5e7; border-radius: 8px; padding: 8px; }}
        QScrollArea {{ border: none; background: white; }}
        QSlider::groove:horizontal {{ height: 4px; background: #dcdfe3; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {PINK}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; background: {PINK}; border-radius: 7px; }}
        QSlider#playerTimeline::groove:horizontal {{ height: 3px; background: rgba(255, 255, 255, 90); border-radius: 1px; }}
        QSlider#playerTimeline::sub-page:horizontal {{ background: #00aeec; border-radius: 1px; }}
        QSlider#playerTimeline::handle:horizontal {{ width: 10px; margin: -4px 0; background: #00aeec; border-radius: 5px; }}
        QSlider#playerTimeline:hover::groove:horizontal {{ height: 5px; }}
        QSlider#playerTimeline:hover::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; }}
        #playerMenu QSlider::groove:horizontal, #playSettings QSlider::groove:horizontal {{ height: 3px; background: #66676a; border-radius: 1px; }}
        #playerMenu QSlider::sub-page:horizontal, #playSettings QSlider::sub-page:horizontal {{ background: #00aeec; border-radius: 1px; }}
        #playerMenu QSlider::handle:horizontal, #playSettings QSlider::handle:horizontal {{ width: 12px; margin: -5px 0; background: white; border-radius: 6px; }}
        QSlider#volumeSlider::groove:vertical {{ width: 3px; background: #66676a; border-radius: 1px; }}
        QSlider#volumeSlider::sub-page:vertical {{ background: #66676a; border-radius: 1px; }}
        QSlider#volumeSlider::add-page:vertical {{ background: #00aeec; border-radius: 1px; }}
        QSlider#volumeSlider::handle:vertical {{ height: 12px; margin: 0 -5px; background: white; border-radius: 6px; }}
        """
    )
