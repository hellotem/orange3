from AnyQt.QtWidgets import QComboBox, QTextEdit, QMessageBox, QApplication
from AnyQt.QtGui import QCursor
from AnyQt.QtCore import Qt

from Orange.data import Table
from Orange.data.sql.backend import Backend
from Orange.data.sql.backend.base import BackendError
from Orange.data.sql.table import SqlTable, LARGE_TABLE, AUTO_DL_LIMIT
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.itemmodels import PyListModel
from Orange.widgets.utils.owbasesql import OWBaseSql
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Output, Msg

MAX_DL_LIMIT = 1000000


def is_postgres(backend):
    return getattr(backend, 'display_name', '') == "PostgreSQL"


class TableModel(PyListModel):
    def data(self, index, role=Qt.DisplayRole):
        row = index.row()
        if role == Qt.DisplayRole:
            return str(self[row])
        return super().data(index, role)


class BackendModel(PyListModel):
    def data(self, index, role=Qt.DisplayRole):
        row = index.row()
        if role == Qt.DisplayRole:
            return self[row].display_name
        return super().data(index, role)


class OWSql(OWBaseSql):
    name = "SQL 表 SQL Table"
    id = "orange.widgets.data.sql"
    description = "从 SQL 加载数据集。"
    icon = "icons/SQLTable.svg"
    priority = 30
    category = "数据"
    keywords = "sql 表,加载"

    class Outputs:
        data = Output("数据", Table, doc="从输入文件读取的属性值数据集。")

    settings_version = 2

    buttons_area_orientation = None

    selected_backend = Setting(None)
    table = Setting(None)
    sql = Setting("")
    guess_values = Setting(True)
    download = Setting(False)

    materialize = Setting(False)
    materialize_table_name = Setting("")

    class Information(OWBaseSql.Information):
        data_sampled = Msg("数据描述是从样本生成的。")

    class Warning(OWBaseSql.Warning):
        missing_extension = Msg("数据库缺少扩展: {}")

    class Error(OWBaseSql.Error):
        no_backends = Msg("请安装后端以使用此小部件。")

    def __init__(self):
        # Lint
        self.backends = None
        self.backendcombo = None
        self.tables = None
        self.tablecombo = None
        self.sqltext = None
        self.custom_sql = None
        self.downloadcb = None
        super().__init__()

    def _setup_gui(self):
        super()._setup_gui()
        self._add_backend_controls()
        self._add_tables_controls()

    def _add_backend_controls(self):
        box = self.serverbox
        self.backends = BackendModel(Backend.available_backends())
        self.backendcombo = QComboBox(box)
        if self.backends:
            self.backendcombo.setModel(self.backends)
            names = [backend.display_name for backend in self.backends]
            if self.selected_backend and self.selected_backend in names:
                self.backendcombo.setCurrentText(self.selected_backend)
        else:
            self.Error.no_backends()
            box.setEnabled(False)
        self.backendcombo.currentTextChanged.connect(self.__backend_changed)
        box.layout().insertWidget(0, self.backendcombo)

    def __backend_changed(self):
        backend = self.get_backend()
        self.selected_backend = backend.display_name if backend else None

    def _add_tables_controls(self):
        vbox = gui.vBox(self.controlArea, "表")
        box = gui.vBox(vbox)
        self.tables = TableModel()

        self.tablecombo = QComboBox(
            minimumContentsLength=35,
            sizeAdjustPolicy=QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.tablecombo.setModel(self.tables)
        self.tablecombo.setToolTip('表')
        self.tablecombo.activated[int].connect(self.select_table)
        box.layout().addWidget(self.tablecombo)

        self.custom_sql = gui.vBox(box)
        self.custom_sql.setVisible(False)
        self.sqltext = QTextEdit(self.custom_sql)
        self.sqltext.setPlainText(self.sql)
        self.custom_sql.layout().addWidget(self.sqltext)

        mt = gui.hBox(self.custom_sql)
        cb = gui.checkBox(mt, self, 'materialize', '实体化为表 ')
        cb.setToolTip('将查询结果保存在表中')
        le = gui.lineEdit(mt, self, 'materialize_table_name')
        le.setToolTip('将查询结果保存在表中')

        gui.button(self.custom_sql, self, '执行', callback=self.open_table)

        box.layout().addWidget(self.custom_sql)

        gui.checkBox(box, self, "guess_values",
                     "自动发现分类变量",
                     callback=self.open_table)

        self.downloadcb = gui.checkBox(box, self, "download",
                                       "下载数据到本地内存",
                                       callback=self.open_table)

    def highlight_error(self, text=""):
        err = ['', 'QLineEdit {border: 2px solid red;}']
        self.servertext.setStyleSheet(err['server' in text or 'host' in text])
        self.usernametext.setStyleSheet(err['role' in text])
        self.databasetext.setStyleSheet(err['database' in text])

    def get_backend(self):
        if self.backendcombo.currentIndex() < 0:
            return None
        return self.backends[self.backendcombo.currentIndex()]

    def on_connection_success(self):
        if getattr(self.backend, 'missing_extension', False):
            self.Warning.missing_extension(
                ", ".join(self.backend.missing_extension))
            self.download = True
            self.downloadcb.setEnabled(False)
        if not is_postgres(self.backend):
            self.download = True
            self.downloadcb.setEnabled(False)
        super().on_connection_success()
        self.refresh_tables()
        self.select_table()

    def on_connection_error(self, err):
        super().on_connection_error(err)
        self.highlight_error(str(err).split("\n")[0])

    def clear(self):
        super().clear()
        self.Warning.missing_extension.clear()
        self.downloadcb.setEnabled(True)
        self.highlight_error()
        self.tablecombo.clear()
        self.tablecombo.repaint()

    def refresh_tables(self):
        self.tables.clear()
        if self.backend is None:
            self.data_desc_table = None
            return

        self.tables.append("选择一个表")
        self.tables.append("自定义 SQL")
        self.tables.extend(self.backend.list_tables(self.schema))
        index = self.tablecombo.findText(str(self.table))
        self.tablecombo.setCurrentIndex(index if index != -1 else 0)
        self.tablecombo.repaint()

    # Called on tablecombo selection change:
    def select_table(self):
        curIdx = self.tablecombo.currentIndex()
        if self.tablecombo.itemText(curIdx) != "自定义 SQL":
            self.custom_sql.setVisible(False)
            return self.open_table()
        else:
            self.custom_sql.setVisible(True)
            self.data_desc_table = None
            self.database_desc["表"] = "(无)"
            self.table = None
            if len(str(self.sql)) > 14:
                return self.open_table()
        return None

    def get_table(self):
        curIdx = self.tablecombo.currentIndex()
        if curIdx <= 0:
            if self.database_desc:
                self.database_desc["Table"] = "(无)"
            self.data_desc_table = None
            return None

        if self.tablecombo.itemText(curIdx) != "自定义 SQL":
            self.table = self.tables[self.tablecombo.currentIndex()]
            self.database_desc["Table"] = self.table
            if "查询" in self.database_desc:
                del self.database_desc["查询"]
            what = self.table
        else:
            what = self.sql = self.sqltext.toPlainText()
            self.table = "自定义 SQL"
            if self.materialize:
                if not self.materialize_table_name:
                    self.Error.connection(
                        "指定一个表名来实体化查询")
                    return None
                try:
                    with self.backend.execute_sql_query("DROP TABLE IF EXISTS " +
                                                        self.materialize_table_name):
                        pass
                    with self.backend.execute_sql_query("CREATE TABLE " +
                                                        self.materialize_table_name +
                                                        " AS " + self.sql):
                        pass
                    with self.backend.execute_sql_query("ANALYZE " + self.materialize_table_name):
                        pass
                except BackendError as ex:
                    self.Error.connection(str(ex))
                    return None

        try:
            table = SqlTable(dict(host=self.host,
                                  port=self.port,
                                  database=self.database,
                                  user=self.username,
                                  password=self.password),
                             what,
                             backend=type(self.backend),
                             inspect_values=False)
        except BackendError as ex:
            self.Error.connection(str(ex))
            return None

        self.Error.connection.clear()

        sample = False

        if table.approx_len() > LARGE_TABLE and self.guess_values:
            confirm = QMessageBox(self)
            confirm.setIcon(QMessageBox.Warning)
            confirm.setText("属性发现可能需要 "
                            "在大表上花费很长时间。\n"
                            "您要自动发现属性吗?")
            confirm.addButton("是", QMessageBox.YesRole)
            no_button = confirm.addButton("否", QMessageBox.NoRole)
            if is_postgres(self.backend):
                sample_button = confirm.addButton("是,在样本上",
                                                  QMessageBox.YesRole)
            confirm.exec()
            if confirm.clickedButton() == no_button:
                self.guess_values = False
            elif is_postgres(self.backend) and \
                    confirm.clickedButton() == sample_button:
                sample = True

        self.Information.clear()
        if self.guess_values:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
            if sample:
                s = table.sample_time(1)
                domain = s.get_domain(inspect_values=True)
                self.Information.data_sampled()
            else:
                domain = table.get_domain(inspect_values=True)
            QApplication.restoreOverrideCursor()
            table.domain = domain

        if self.download:
            if table.approx_len() > AUTO_DL_LIMIT:
                if is_postgres(self.backend):
                    confirm = QMessageBox(self)
                    confirm.setIcon(QMessageBox.Warning)
                    confirm.setText("数据似乎很大。你真的 "
                                    "要下载到本地内存吗?\n"
                                    "表长度: {:,}。限制 {:,}".format(table.approx_len(), MAX_DL_LIMIT))

                    if table.approx_len() <= MAX_DL_LIMIT:
                        confirm.addButton("是", QMessageBox.YesRole)
                    no_button = confirm.addButton("否", QMessageBox.NoRole)
                    sample_button = confirm.addButton("是,一个样本",
                                                      QMessageBox.YesRole)
                    confirm.exec()
                    if confirm.clickedButton() == no_button:
                        return None
                    elif confirm.clickedButton() == sample_button:
                        table = table.sample_percentage(
                            AUTO_DL_LIMIT / table.approx_len() * 100)
                else:
                    if table.approx_len() > MAX_DL_LIMIT:
                        QMessageBox.warning(
                            self, '警告',
                            "数据太大,无法下载。\n"
                            "表长度: {:,}。限制 {:,}".format(table.approx_len(), MAX_DL_LIMIT)
                        )
                        return None
                    else:
                        confirm = QMessageBox.question(
                            self, '问题',
                            "数据似乎很大。你真的 "
                            "要下载到本地内存吗?",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                        if confirm == QMessageBox.No:
                            return None

            table.download_data(MAX_DL_LIMIT)
            table = Table(table)

        return table

    @classmethod
    def migrate_settings(cls, settings, version):
        if version < 2:
            # Until Orange version 3.4.4 username and password had been stored
            # in Settings.
            cm = cls._credential_manager(settings["host"], settings["port"])
            cm.username = settings["username"]
            cm.password = settings["password"]


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWSql).run()
