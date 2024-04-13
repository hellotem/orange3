from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QFormLayout, QCheckBox, QLineEdit, QWidget, QVBoxLayout, QLabel
)
from orangecanvas.application.settings import UserSettingsDialog, FormLayout
from orangecanvas.document.interactions import PluginDropHandler
from orangecanvas.document.usagestatistics import UsageStatistics
from orangecanvas.utils.overlay import NotificationOverlay

from orangewidget.workflow.mainwindow import OWCanvasMainWindow


class OUserSettingsDialog(UserSettingsDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        w = self.widget(0)  # 'General' tab
        layout = w.layout()
        assert isinstance(layout, QFormLayout)
        cb = QCheckBox(self.tr("自动检查更新"))
        cb.setAttribute(Qt.WA_LayoutUsesWidgetRect)

        layout.addRow("更新", cb)
        self.bind(cb, "checked", "startup/check-updates")

        # Reporting Tab
        tab = QWidget()
        self.addTab(tab, self.tr("报告"),
                    toolTip="与报告相关的设置")

        form = FormLayout()
        line_edit_mid = QLineEdit()
        self.bind(line_edit_mid, "text", "reporting/machine-id")
        form.addRow("Machine ID:", line_edit_mid)

        box = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        cb1 = QCheckBox(
            self.tr("分享"),
            toolTip=self.tr(
                "分享匿名使用统计数据以改进Orange")
        )
        self.bind(cb1, "checked", "reporting/send-statistics")
        cb1.clicked.connect(UsageStatistics.set_enabled)
        layout.addWidget(cb1)
        box.setLayout(layout)
        form.addRow(self.tr("匿名统计"), box)
        label = QLabel("<a "
                       "href=\"https://orange.biolab.si/statistics-more-info\">"
                       "更多信息..."
                       "</a>")
        label.setOpenExternalLinks(True)
        form.addRow(self.tr(""), label)

        tab.setLayout(form)

        # Notifications Tab
        tab = QWidget()
        self.addTab(tab, self.tr("通知"),
                    toolTip="与通知相关的设置")

        form = FormLayout()

        box = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox(
            self.tr("启用通知"), self,
            toolTip="拉取和显示通知源。"
        )
        self.bind(cb, "checked", "notifications/check-notifications")

        layout.addWidget(cb)
        box.setLayout(layout)
        form.addRow(self.tr("启动时"), box)

        notifs = QWidget(self, objectName="notifications-group")
        notifs.setLayout(QVBoxLayout())
        notifs.layout().setContentsMargins(0, 0, 0, 0)

        cb1 = QCheckBox(self.tr("公告"), self,
                        toolTip="显示有关Biolab公告的通知。\n"
                                "这包括由Orange的开发者举办的"
                                "活动和课程。")

        cb2 = QCheckBox(self.tr("博客文章"), self,
                        toolTip="显示有关博客文章的通知。\n"
                                "我们只会发送精华内容。")
        cb3 = QCheckBox(self.tr("新功能"), self,
                        toolTip="当新版本下载并安装后,"
                                "显示有关Orange新功能的通知,\n"
                                "如果新版本包含显著更新。")

        self.bind(cb1, "checked", "notifications/announcements")
        self.bind(cb2, "checked", "notifications/blog")
        self.bind(cb3, "checked", "notifications/new-features")

        notifs.layout().addWidget(cb1)
        notifs.layout().addWidget(cb2)
        notifs.layout().addWidget(cb3)

        form.addRow(self.tr("显示通知内容:"), notifs)
        tab.setLayout(form)


class MainWindow(OWCanvasMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notification_overlay = NotificationOverlay(self.scheme_widget)
        self.notification_server = None
        self.scheme_widget.setDropHandlers([
            PluginDropHandler("orange.canvas.drophandler")
        ])

    def open_canvas_settings(self):
        # type: () -> None
        """Reimplemented."""
        dlg = OUserSettingsDialog(self, windowTitle=self.tr("首选项"))
        dlg.show()
        status = dlg.exec()
        if status == 0:
            self.user_preferences_changed_notify_all()

    def set_notification_server(self, notif_server):
        self.notification_server = notif_server

        # populate notification overlay with current notifications
        for notif in self.notification_server.getNotificationQueue():
            self.notification_overlay.addNotification(notif)

        notif_server.newNotification.connect(self.notification_overlay.addNotification)
        notif_server.nextNotification.connect(self.notification_overlay.nextWidget)

    def create_new_window(self):  # type: () -> CanvasMainWindow
        window = super().create_new_window()
        window.set_notification_server(self.notification_server)
        return window
