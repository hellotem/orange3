from typing import Dict, Tuple
from types import SimpleNamespace

import numpy as np

from AnyQt.QtCore import Signal, Qt
from AnyQt.QtWidgets import QWidget, QVBoxLayout

from orangewidget.report import bool_str
from orangewidget.settings import SettingProvider

from Orange.base import Learner
from Orange.classification import OneClassSVMLearner, EllipticEnvelopeLearner,\
    LocalOutlierFactorLearner, IsolationForestLearner
from Orange.data import Table
from Orange.util import wrap_callback
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.concurrent import TaskState, ConcurrentWidgetMixin
from Orange.widgets.utils.sql import check_sql_input
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Msg, Input, Output, OWWidget


class Results(SimpleNamespace):
    inliers = None  # type: Optional[Table]
    outliers = None  # type: Optional[Table]
    annotated_data = None  # type: Optional[Table]


def run(data: Table, learner: Learner, state: TaskState) -> Results:
    results = Results()
    if not data:
        return results

    def callback(i: float, status=""):
        state.set_progress_value(i * 100)
        if status:
            state.set_status(status)
        if state.is_interruption_requested():
            raise Exception

    callback(0, "初始化...")
    model = learner(data, wrap_callback(callback, end=0.6))
    pred = model(data, wrap_callback(callback, start=0.6, end=0.99))

    col = pred.get_column(model.outlier_var)
    inliers_ind = np.where(col == 1)[0]
    outliers_ind = np.where(col == 0)[0]

    results.inliers = data[inliers_ind]
    results.outliers = data[outliers_ind]
    results.annotated_data = pred
    callback(1)
    return results


class ParametersEditor(QWidget, gui.OWComponent):
    param_changed = Signal()

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        gui.OWComponent.__init__(self, parent)

        self.setMinimumWidth(300)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.param_box = gui.vBox(self, spacing=0)

    def parameter_changed(self):
        self.param_changed.emit()

    def get_parameters(self) -> Dict:
        raise NotImplementedError


class SVMEditor(ParametersEditor):
    nu = Setting(50)
    gamma = Setting(0.01)

    def __init__(self, parent):
        super().__init__(parent)

        tooltip = "训练误差和" \
                  "支持向量分数的下限"
        gui.widgetLabel(self.param_box, "Nu:", tooltip=tooltip)
        gui.hSlider(self.param_box, self, "nu", minValue=1, maxValue=100,
                    ticks=10, labelFormat="%d %%", tooltip=tooltip,
                    callback=self.parameter_changed)
        gui.doubleSpin(self.param_box, self, "gamma",
                       label="Kernel coefficient:", step=1e-2, minv=0.01,
                       maxv=10, callback=self.parameter_changed)

    def get_parameters(self):
        return {"nu": self.nu / 100,
                "gamma": self.gamma}

    def get_report_parameters(self):
        return {"检测方法": "具有非线性内核(RBF)的单类SVM",
                 "正则化(nu)": f"{self.nu/100:.0%}",
                 "内核系数": self.gamma}


class CovarianceEditor(ParametersEditor):
    cont = Setting(10)
    empirical_covariance = Setting(False)
    support_fraction = Setting(1)

    def __init__(self, parent):
        super().__init__(parent)

        gui.widgetLabel(self.param_box, "Contamination:")
        gui.hSlider(self.param_box, self, "cont", minValue=0,
                    maxValue=100, ticks=10, labelFormat="%d %%",
                    callback=self.parameter_changed)

        ebox = gui.hBox(self.param_box)
        gui.checkBox(ebox, self, "empirical_covariance",
                     "Support fraction:", callback=self.parameter_changed)
        gui.doubleSpin(ebox, self, "support_fraction", step=1e-1,
                       minv=0.1, maxv=10, callback=self.parameter_changed)

    def get_parameters(self):
        fraction = self.support_fraction if self.empirical_covariance else None
        return {"contamination": self.cont / 100,
                "support_fraction": fraction}

    def get_report_parameters(self):
        fraction = self.support_fraction if self.empirical_covariance else None
        return {"检测方法": "协方差估计",
                "污染": f"{self.cont/100:.0%}",
                 "支持分数": fraction}


class LocalOutlierFactorEditor(ParametersEditor):
    METRICS = ("euclidean", "manhattan", "cosine", "jaccard",
               "hamming", "minkowski")
    METRICS_NAMES = ["欧几里得", "曼哈顿", "余弦", "杰卡德", "汉明", "明科夫斯基"]

    n_neighbors = Setting(20)
    cont = Setting(10)
    metric_index = Setting(0)

    def __init__(self, parent):
        super().__init__(parent)

        gui.widgetLabel(self.param_box, "Contamination:")
        gui.hSlider(self.param_box, self, "cont", minValue=1,
                    maxValue=50, ticks=5, labelFormat="%d %%",
                    callback=self.parameter_changed)
        gui.spin(self.param_box, self, "n_neighbors", label="Neighbors:",
                 minv=1, maxv=100000, callback=self.parameter_changed)
        gui.comboBox(self.param_box, self, "metric_index", label="Metric:",
                     orientation=Qt.Horizontal,
                     items=self.METRICS_NAMES,
                     callback=self.parameter_changed)

    def get_parameters(self):
        return {"n_neighbors": self.n_neighbors,
                "contamination": self.cont / 100,
                "algorithm": "brute",  # works faster for big datasets
                # pylint: disable=invalid-sequence-index
                "metric": self.METRICS[self.metric_index]}

    def get_report_parameters(self):
        return {"检测方法": "局部异常因子",
                 "污染": f"{self.cont/100:.0%}",
                 "邻居数量": self.n_neighbors,
                 # pylint: disable=invalid-sequence-index
                 "度量": self.METRICS_NAMES[self.metric_index]}


class IsolationForestEditor(ParametersEditor):
    cont = Setting(10)
    replicable = Setting(False)

    def __init__(self, parent):
        super().__init__(parent)

        gui.widgetLabel(self.param_box, "Contamination:")
        gui.hSlider(self.param_box, self, "cont", minValue=0,
                    maxValue=100, ticks=10, labelFormat="%d %%",
                    callback=self.parameter_changed)
        gui.checkBox(self.param_box, self, "replicable",
                     "可复制训练", callback=self.parameter_changed)

    def get_parameters(self):
        return {"contamination": self.cont / 100,
                "random_state": 42 if self.replicable else None}

    def get_report_parameters(self):
        return {"检测方法": "隔离森林",
                "污染": f"{self.cont/100:.0%}",
                "可复制训练": bool_str(self.replicable)}

class OWOutliers(OWWidget, ConcurrentWidgetMixin):
    name = "异常值 Outliers"
    description = "检测异常值。"
    icon = "icons/Outliers.svg"
    priority = 3000
    category = "无监督"
    keywords = "异常值,内层"

    class Inputs:
        data = Input("数据", Table)

    class Outputs:
        inliers = Output("内层", Table)
        outliers = Output("异常值", Table)
        data = Output("数据", Table)

    want_main_area = False
    resizing_enabled = False

    OneClassSVM, Covariance, LOF, IsolationForest = range(4)
    METHODS = (OneClassSVMLearner, EllipticEnvelopeLearner,
               LocalOutlierFactorLearner, IsolationForestLearner)
    svm_editor = SettingProvider(SVMEditor)
    cov_editor = SettingProvider(CovarianceEditor)
    lof_editor = SettingProvider(LocalOutlierFactorEditor)
    isf_editor = SettingProvider(IsolationForestEditor)

    settings_version = 2
    outlier_method = Setting(LOF)
    auto_commit = Setting(True)

    MAX_FEATURES = 1500

    class Warning(OWWidget.Warning):
        disabled_cov = Msg("协方差估计的特征太多。")

    class Error(OWWidget.Error):
        singular_cov = Msg("奇异协方差矩阵。")
        memory_error = Msg("内存不足")

    def __init__(self):
        OWWidget.__init__(self)
        ConcurrentWidgetMixin.__init__(self)
        self.data = None  # type: Table
        self.n_inliers = None  # type: int
        self.n_outliers = None  # type: int
        self.editors = None  # type: Tuple[ParametersEditor]
        self.current_editor = None  # type: ParametersEditor
        self.method_combo = None  # type: QComboBox
        self.init_gui()

    def init_gui(self):
        box = gui.vBox(self.controlArea, "方法")
        self.method_combo = gui.comboBox(box, self, "outlier_method",
                                         items=[m.name for m in self.METHODS],
                                         callback=self.__method_changed)

        self._init_editors()

        gui.auto_apply(self.buttonsArea, self, "auto_commit")

    def _init_editors(self):
        self.svm_editor = SVMEditor(self)
        self.cov_editor = CovarianceEditor(self)
        self.lof_editor = LocalOutlierFactorEditor(self)
        self.isf_editor = IsolationForestEditor(self)

        box = gui.vBox(self.controlArea, "参数")
        self.editors = (self.svm_editor, self.cov_editor,
                        self.lof_editor, self.isf_editor)
        for editor in self.editors:
            editor.param_changed.connect(self.commit.deferred)
            box.layout().addWidget(editor)
            editor.hide()

        self.set_current_editor()

    def __method_changed(self):
        self.set_current_editor()
        self.commit.deferred()

    def set_current_editor(self):
        if self.current_editor:
            self.current_editor.hide()
        self.current_editor = self.editors[self.outlier_method]
        self.current_editor.show()

    @Inputs.data
    @check_sql_input
    def set_data(self, data):
        self.cancel()
        self.clear_messages()
        self.data = data
        self.enable_controls()
        self.commit.now()

    def enable_controls(self):
        self.method_combo.model().item(self.Covariance).setEnabled(True)
        if self.data and len(self.data.domain.attributes) > self.MAX_FEATURES:
            self.outlier_method = self.LOF
            self.set_current_editor()
            self.method_combo.model().item(self.Covariance).setEnabled(False)
            self.Warning.disabled_cov()

    @gui.deferred
    def commit(self):
        self.Error.singular_cov.clear()
        self.Error.memory_error.clear()
        self.n_inliers = self.n_outliers = None

        learner_class = self.METHODS[self.outlier_method]
        kwargs = self.current_editor.get_parameters()
        learner = learner_class(**kwargs)

        self.start(run, self.data, learner)

    def on_partial_result(self, _):
        pass

    def on_done(self, result: Results):
        inliers, outliers = result.inliers, result.outliers
        self.n_inliers = len(inliers) if inliers else None
        self.n_outliers = len(outliers) if outliers else None

        self.Outputs.inliers.send(inliers)
        self.Outputs.outliers.send(outliers)
        self.Outputs.data.send(result.annotated_data)

    def on_exception(self, ex):
        if isinstance(ex, ValueError):
            self.Error.singular_cov(ex)
        elif isinstance(ex, MemoryError):
            self.Error.memory_error()
        else:
            raise ex

    def onDeleteWidget(self):
        self.shutdown()
        super().onDeleteWidget()

    def send_report(self):
        if self.data is not None:
            if self.n_outliers is None or self.n_inliers is None:
                return
            self.report_items("数据",
                              (("输入实例", len(self.data)),
                               ("内层", self.n_inliers),
                               ("异常值", self.n_outliers)))
        self.report_items("检测",
                          self.current_editor.get_report_parameters())

    @classmethod
    def migrate_settings(cls, settings: Dict, version: int):
        if version is None or version < 2:
            settings["svm_editor"] = {"nu": settings.get("nu", 50),
                                      "gamma": settings.get("gamma", 0.01)}
            ec, sf = "empirical_covariance", "support_fraction"
            settings["cov_editor"] = {"cont": settings.get("cont", 10),
                                      ec: settings.get(ec, False),
                                      sf: settings.get(sf, 1)}


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWOutliers).run(Table("iris"))
