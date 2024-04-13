import os

import numpy as np

from AnyQt.QtWidgets import QSizePolicy, QStyle, QMessageBox, QFileDialog
from AnyQt.QtCore import QTimer

from orangewidget.settings import Setting
from orangewidget.widget import Msg
from orangewidget.workflow.drophandler import SingleFileDropHandler

from Orange.misc import DistMatrix
from Orange.widgets import widget, gui
from Orange.data import get_sample_datasets_dir
from Orange.widgets.utils.filedialogs import RecentPathsWComboMixin, RecentPath, \
    stored_recent_paths_prepend
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Output


class OWDistanceFile(widget.OWWidget, RecentPathsWComboMixin):
    name = "距离文件 Distance File"
    id = "orange.widgets.unsupervised.distancefile"
    description = "从文件读取距离。"
    icon = "icons/DistanceFile.svg"
    priority = 10
    keywords = "distance file, load, read, open"

    class Outputs:
        distances = Output("距离", DistMatrix, dynamic=False)

    class Error(widget.OWWidget.Error):
        invalid_file = Msg("数据未加载:{}")
        non_square_matrix = Msg(
            "矩阵不是方阵。"
            "重新格式化文件并使用文件部件读取。")

    want_main_area = False
    resizing_enabled = False

    auto_symmetric = Setting(True)

    def __init__(self):
        super().__init__()
        RecentPathsWComboMixin.__init__(self)
        self.distances = None

        vbox = gui.vBox(self.controlArea, "距离文件")
        box = gui.hBox(vbox)
        self.file_combo.setMinimumWidth(300)
        box.layout().addWidget(self.file_combo)
        self.file_combo.activated[int].connect(self.select_file)

        button = gui.button(box, self, '...', callback=self.browse_file)
        button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        button.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed)

        button = gui.button(
            box, self, "重新加载", callback=self.reload, default=True)
        button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        vbox = gui.vBox(self.controlArea, "选项")
        gui.checkBox(
            vbox, self, "auto_symmetric",
            "将三角矩阵视为对称矩阵",
            tooltip="如果矩阵是三角形的,这将复制数据到"
                    "另一个三角形",
            callback=self.commit
        )

        gui.rubber(self.buttonsArea)
        gui.button(
            self.buttonsArea, self, "浏览文档数据集",
            callback=lambda: self.browse_file(True), autoDefault=False)
        gui.rubber(self.buttonsArea)

        self.set_file_list()
        QTimer.singleShot(0, self.open_file)

    def set_file_list(self):
        super().set_file_list()

    def reload(self):
        return self.open_file()

    def select_file(self, n):
        super().select_file(n)
        self.set_file_list()
        self.open_file()

    def browse_file(self, in_demos=False):
        if in_demos:
            start_file = get_sample_datasets_dir()
            if not os.path.exists(start_file):
                QMessageBox.information(
                    None, "文件",
                    "无法找到包含文档数据集的目录")
                return
        else:
            start_file = self.last_path() or os.path.expanduser("~/")

        filename, _ = QFileDialog.getOpenFileName(
            self, '打开距离文件', start_file,
            "Excel 文件 (*.xlsx);;距离文件 (*.dst)")
        if not filename:
            return
        self.add_path(filename)
        self.open_file()

    def open_file(self):
        self.Error.clear()
        self.distances = None
        fn = self.last_path()
        if fn and not os.path.exists(fn):
            dir_name, basename = os.path.split(fn)
            if os.path.exists(os.path.join(".", basename)):
                fn = os.path.join(".", basename)
        if fn and fn != "(无)":
            try:
                distances = DistMatrix.from_file(fn)
            except Exception as exc:
                err = str(exc)
                self.Error.invalid_file(" \n"[len(err) > 40] + err)
            else:
                if distances.shape[0] != distances.shape[1]:
                    self.Error.non_square_matrix()
                else:
                    np.nan_to_num(distances)
                    self.distances = distances
                    _, filename = os.path.split(fn)
                    self.distances.name, _ = os.path.splitext(filename)
        self.commit()

    def commit(self):
        distances = self.distances
        if distances is not None:
            if self.auto_symmetric:
                distances = distances.auto_symmetricized()
            if np.any(np.isnan(distances)):
                distances = np.nan_to_num(distances)
        self.Outputs.distances.send(distances)

    def send_report(self):
        if not self.distances:
            self.report_paragraph("未加载任何数据。")
        else:
            self.report_items([("文件名", self.distances.name)])


class OWDistanceFileDropHandler(SingleFileDropHandler):
    WIDGET = OWDistanceFile

    def parametersFromFile(self, path):
        r = RecentPath(os.path.abspath(path), None, None,
                       os.path.basename(path))
        return {"recent_paths": stored_recent_paths_prepend(self.WIDGET, r)}

    def canDropFile(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() in (".dst", ".xlsx")


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWDistanceFile).run()
