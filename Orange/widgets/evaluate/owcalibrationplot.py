from collections import namedtuple

import numpy as np

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QListWidget

import pyqtgraph as pg

from orangewidget.utils.visual_settings_dlg import VisualSettingsDialog

from Orange.base import Model
from Orange.classification import ThresholdClassifier, CalibratedLearner
from Orange.evaluation import Results
from Orange.evaluation.performance_curves import Curves
from Orange.widgets import widget, gui, settings
from Orange.widgets.evaluate.contexthandlers import \
    EvaluationResultsContextHandler
from Orange.widgets.evaluate.utils import results_for_preview, \
    check_can_calibrate
from Orange.widgets.utils import colorpalettes
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.visualize.utils.customizableplot import \
    CommonParameterSetter
from Orange.widgets.visualize.utils.plotutils import GraphicsView, PlotItem
from Orange.widgets.widget import Input, Output, Msg
from Orange.widgets import report


MetricDefinition = namedtuple(
    "metric_definition",
    ("name", "functions", "short_names", "explanation"))

Metrics = [MetricDefinition(*args) for args in (
    ("校准曲线", None, (), ""),
    ("分类准确率", (Curves.ca, ), (), ""),
    ("F1 分数", (Curves.f1, ), (), ""),
    ("敏感性和特异性",
     (Curves.sensitivity, Curves.specificity),
     ("敏感性", "特异性"),
     "<p><b>敏感性</b>(下降)是正确检测 "
     "阳性实例的比例(TP&nbsp;/&nbsp;P)。</p>"
     "<p><b>特异性</b>(上升)是检测 "
     "阴性实例的比例(TN&nbsp;/&nbsp;N)。</p>"),
    ("精确率和召回率",
     (Curves.precision, Curves.recall),
     ("精确率 ", "召回率"),
     "<p><b>精确率</b>(上升)是检索实例 "
     "相关性的比例, TP&nbsp;/&nbsp;(TP&nbsp;+&nbsp;FP)。</p>"
     "<p><b>召回率</b>(下降)是发现相关 "
     "实例的比例, TP&nbsp;/&nbsp;P。</p>"),
    ("阳性和阴性预测值",
     (Curves.ppv, Curves.npv),
     ("阳性预测值", "真阴性值"),
     "<p><b>阳性预测值</b>(上升)是 "
     "正确阳性的比例, TP&nbsp;/&nbsp;(TP&nbsp;+&nbsp;FP)。</p>"
     "<p><b>阴性预测值</b>是正确 "
     "阴性的比例, TN&nbsp;/&nbsp;(TN&nbsp;+&nbsp;FN)。</p>"),
    ("真阳性率和假阳性率",
     (Curves.tpr, Curves.fpr),
     ("真阳性率", "假阳性率"),
     "<p><b>真阳性率和假阳性率</b>是检测 "
     "和遗漏阳性实例的比例</p>"),
)]


class ParameterSetter(CommonParameterSetter):

    def __init__(self, master):
        super().__init__()
        self.master = master

    def update_setters(self):
        self.initial_settings = {
            self.LABELS_BOX: {
                self.FONT_FAMILY_LABEL: self.FONT_FAMILY_SETTING,
                self.TITLE_LABEL: self.FONT_SETTING,
                self.AXIS_TITLE_LABEL: self.FONT_SETTING,
                self.AXIS_TICKS_LABEL: self.FONT_SETTING,
            },
            self.ANNOT_BOX: {
                self.TITLE_LABEL: {self.TITLE_LABEL: ("", "")},
            }
        }

    @property
    def title_item(self):
        return self.master.titleLabel

    @property
    def axis_items(self):
        return [value["item"] for value in self.master.axes.values()]


class OWCalibrationPlot(widget.OWWidget):
    name = "校准曲线图 Calibration Plot"
    description = "基于分类器评估的校准曲线图。"
    icon = "icons/CalibrationPlot.svg"
    priority = 1030
    keywords = "校准曲线图"

    class Inputs:
        evaluation_results = Input("评估结果", Results)

    class Outputs:
        calibrated_model = Output("校准模型", Model)

    class Error(widget.OWWidget.Error):
        non_discrete_target = Msg("校准曲线需要分类 "
                                  "目标变量。")
        empty_input = widget.Msg("输入结果为空。无需显示。")
        nan_classes = \
            widget.Msg("删除具有未知类的测试数据实例。")
        all_target_class = widget.Msg(
            "所有数据实例都属于目标类。")
        no_target_class = widget.Msg(
            "没有数据实例属于目标类。")

    class Warning(widget.OWWidget.Warning):
        omitted_folds = widget.Msg(
            "所有数据属于(非)目标的测试折叠未显示。")
        omitted_nan_prob_points = widget.Msg(
            "模型无法计算概率的实例会"
            "跳过。")
        no_valid_data = widget.Msg("模型 {} 没有有效数据")

    class Information(widget.OWWidget.Information):
        no_output = Msg("无法输出模型: {}")

    settingsHandler = EvaluationResultsContextHandler()
    target_index = settings.ContextSetting(0)
    selected_classifiers = settings.ContextSetting([])
    score = settings.Setting(0)
    output_calibration = settings.Setting(0)
    fold_curves = settings.Setting(False)
    display_rug = settings.Setting(True)
    threshold = settings.Setting(0.5)
    visual_settings = settings.Setting({}, schema_only=True)
    auto_commit = settings.Setting(True)

    graph_name = "plot"  # pg.GraphicsItem (pg.PlotItem)

    def __init__(self):
        super().__init__()

        self.results = None
        self.scores = None
        self.classifier_names = []
        self.colors = []
        self.line = None

        self._last_score_value = -1

        box = gui.vBox(self.controlArea, box="设置")
        self.target_cb = gui.comboBox(
            box, self, "target_index", label="Target:",
            orientation=Qt.Horizontal, callback=self.target_index_changed,
            contentsLength=8, searchable=True)
        gui.checkBox(
            box, self, "display_rug", "显示小横纹",
            callback=self._on_display_rug_changed)
        gui.checkBox(
            box, self, "fold_curves", "单个折叠的曲线",
            callback=self._replot)

        self.classifiers_list_box = gui.listBox(
            self.controlArea, self, "selected_classifiers", "classifier_names",
            box="分类器", selectionMode=QListWidget.ExtendedSelection,
            callback=self._on_selection_changed)
        self.classifiers_list_box.setMaximumHeight(100)

        box = gui.vBox(self.controlArea, "指标")
        combo = gui.comboBox(
            box, self, "score", items=(metric.name for metric in Metrics),
            callback=self.score_changed)

        self.explanation = gui.widgetLabel(
            box, wordWrap=True, fixedWidth=combo.sizeHint().width())
        self.explanation.setContentsMargins(8, 8, 0, 0)
        font = self.explanation.font()
        font.setPointSizeF(0.85 * font.pointSizeF())
        self.explanation.setFont(font)

        gui.radioButtons(
            box, self, value="output_calibration",
            btnLabels=("Sigmoid 校准", "等渗校准"),
            label="输出模型校准", callback=self.commit.deferred)

        self.info_box = gui.widgetBox(self.controlArea, "信息")
        self.info_label = gui.widgetLabel(self.info_box)

        gui.rubber(self.controlArea)

        gui.auto_apply(self.buttonsArea, self, "auto_commit")

        self.plotview = GraphicsView()
        self.plot = PlotItem(enableMenu=False)
        self.plot.parameter_setter = ParameterSetter(self.plot)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            # Remove the condition (that is, allow setting this for bottom
            # axis) when pyqtgraph is fixed
            # Issue: https://github.com/pyqtgraph/pyqtgraph/issues/930
            # Pull request: https://github.com/pyqtgraph/pyqtgraph/pull/932
            if axis_name != "bottom":  # remove if when pyqtgraph is fixed
                axis.setStyle(stopAxisAtTick=(True, True))

        self.plot.setRange(xRange=(0.0, 1.0), yRange=(0.0, 1.0), padding=0.05)
        self.plotview.setCentralItem(self.plot)

        self.mainArea.layout().addWidget(self.plotview)
        self._set_explanation()

        VisualSettingsDialog(self, self.plot.parameter_setter.initial_settings)

    @Inputs.evaluation_results
    def set_results(self, results):
        self.closeContext()
        self.clear()
        self.Error.clear()
        self.Information.clear()

        self.results = None
        if results is not None:
            if not results.domain.has_discrete_class:
                self.Error.non_discrete_target()
            elif not results.actual.size:
                self.Error.empty_input()
            elif np.any(np.isnan(results.actual)):
                self.Error.nan_classes()
            else:
                self.results = results
                self._initialize(results)
                class_var = self.results.domain.class_var
                self.target_index = int(len(class_var.values) == 2)
                self.openContext(class_var, self.classifier_names)
                self._replot()

        self.commit.now()

    def clear(self):
        self.plot.clear()
        self.results = None
        self.classifier_names = []
        self.selected_classifiers = []
        self.target_cb.clear()
        self.colors = []

    def target_index_changed(self):
        if len(self.results.domain.class_var.values) == 2:
            self.threshold = 1 - self.threshold
        self._set_explanation()
        self._replot()
        self.commit.deferred()

    def score_changed(self):
        self._set_explanation()
        self._replot()
        if self._last_score_value != self.score:
            self.commit.deferred()
            self._last_score_value = self.score

    def _set_explanation(self):
        explanation = Metrics[self.score].explanation
        if explanation:
            self.explanation.setText(explanation)
            self.explanation.show()
        else:
            self.explanation.hide()

        if self.score == 0:
            self.controls.output_calibration.show()
            self.info_box.hide()
        else:
            self.controls.output_calibration.hide()
            self.info_box.show()

        axis = self.plot.getAxis("bottom")
        axis.setLabel("预测概率" if self.score == 0
                      else "分类为正的概率阈值")

        axis = self.plot.getAxis("left")
        axis.setLabel(Metrics[self.score].name)

    def _initialize(self, results):
        n = len(results.predicted)
        names = getattr(results, "learner_names", None)
        if names is None:
            names = ["#{}".format(i + 1) for i in range(n)]

        self.classifier_names = names
        self.colors = colorpalettes.get_default_curve_colors(n)

        for i in range(n):
            item = self.classifiers_list_box.item(i)
            item.setIcon(colorpalettes.ColorIcon(self.colors[i]))

        self.selected_classifiers = list(range(n))
        self.target_cb.addItems(results.domain.class_var.values)
        self.target_index = 0

    def _rug(self, data, pen_args):
        color = pen_args["pen"].color()
        rh = 0.025
        rug_x = np.c_[data.probs[:-1], data.probs[:-1]]
        rug_x_true = rug_x[data.ytrue].ravel()
        rug_x_false = rug_x[~data.ytrue].ravel()

        rug_y_true = np.ones_like(rug_x_true)
        rug_y_true[1::2] = 1 - rh
        rug_y_false = np.zeros_like(rug_x_false)
        rug_y_false[1::2] = rh

        self.plot.plot(
            rug_x_false, rug_y_false,
            pen=color, connect="pairs", antialias=True)
        self.plot.plot(
            rug_x_true, rug_y_true,
            pen=color, connect="pairs", antialias=True)

    def plot_metrics(self, data, metrics, pen_args):
        if metrics is None:
            return self._prob_curve(data.ytrue, data.probs[:-1], pen_args)
        ys = [metric(data) for metric in metrics]
        for y in ys:
            self.plot.plot(data.probs, y, **pen_args)
        return data.probs, ys

    def _prob_curve(self, ytrue, probs, pen_args):
        xmin, xmax = probs.min(), probs.max()
        x = np.linspace(xmin, xmax, 100)
        if xmax != xmin:
            f = gaussian_smoother(probs, ytrue, sigma=0.15 * (xmax - xmin))
            y = f(x)
        else:
            y = np.full(100, xmax)

        self.plot.plot(x, y, symbol="+", symbolSize=4, **pen_args)
        return x, (y, )

    def _setup_plot(self):
        target = self.target_index
        results = self.results
        metrics = Metrics[self.score].functions
        plot_folds = self.fold_curves and results.folds is not None
        self.scores = []

        if not self._check_class_presence(results.actual == target):
            return

        self.Warning.omitted_folds.clear()
        self.Warning.omitted_nan_prob_points.clear()
        no_valid_models = []
        shadow_width = 4 + 4 * plot_folds
        for clsf in self.selected_classifiers:
            data = Curves.from_results(results, target, clsf)
            if data.tot == 0:  # all probabilities are nan
                no_valid_models.append(clsf)
                continue
            if data.tot != results.probabilities.shape[1]:  # some are nan
                self.Warning.omitted_nan_prob_points()

            color = self.colors[clsf]
            pen_args = dict(
                pen=pg.mkPen(color, width=1), antiAlias=True,
                shadowPen=pg.mkPen(color.lighter(160), width=shadow_width))
            self.scores.append(
                (self.classifier_names[clsf],
                 self.plot_metrics(data, metrics, pen_args)))

            if self.display_rug:
                self._rug(data, pen_args)

            if plot_folds:
                pen_args = dict(
                    pen=pg.mkPen(color, width=1, style=Qt.DashLine),
                    antiAlias=True)
                for fold in range(len(results.folds)):
                    fold_results = results.get_fold(fold)
                    fold_curve = Curves.from_results(fold_results, target, clsf)
                    # Can't check this before: p and n can be 0 because of
                    # nan probabilities
                    if fold_curve.p * fold_curve.n == 0:
                        self.Warning.omitted_folds()
                    self.plot_metrics(fold_curve, metrics, pen_args)

        if no_valid_models:
            self.Warning.no_valid_data(
                ", ".join(self.classifier_names[i] for i in no_valid_models))

        if self.score == 0:
            self.plot.plot([0, 1], [0, 1], antialias=True)
        else:
            self.line = pg.InfiniteLine(
                pos=self.threshold, movable=True,
                pen=pg.mkPen(color="k", style=Qt.DashLine, width=2),
                hoverPen=pg.mkPen(color="k", style=Qt.DashLine, width=3),
                bounds=(0, 1),
            )
            self.line.sigPositionChanged.connect(self.threshold_change)
            self.line.sigPositionChangeFinished.connect(
                self.threshold_change_done)
            self.plot.addItem(self.line)

    def _check_class_presence(self, ytrue):
        self.Error.all_target_class.clear()
        self.Error.no_target_class.clear()
        if np.max(ytrue) == 0:
            self.Error.no_target_class()
            return False
        if np.min(ytrue) == 1:
            self.Error.all_target_class()
            return False
        return True

    def _replot(self):
        self.plot.clear()
        if self.results is not None:
            self._setup_plot()
        self._update_info()

    def _on_display_rug_changed(self):
        self._replot()

    def _on_selection_changed(self):
        self._replot()
        self.commit.deferred()

    def threshold_change(self):
        self.threshold = round(self.line.pos().x(), 2)
        self.line.setPos(self.threshold)
        self._update_info()

    def get_info_text(self, short):
        if short:
            def elided(s):
                return s[:17] + "..." if len(s) > 20 else s

            text = f"""<table>
                            <tr>
                                <th align='right'>Threshold: p=</th>
                                <td colspan='4'>{self.threshold:.2f}<br/></td>
                            </tr>"""

        else:
            def elided(s):
                return s

            text = f"""<table>
                            <tr>
                                <th align='right'>Threshold:</th>
                                <td colspan='4'>p = {self.threshold:.2f}<br/>
                                </td>
                                <tr/>
                            </tr>"""

        if self.scores is not None:
            short_names = Metrics[self.score].short_names
            if short_names:
                text += f"""<tr>
                                <th></th>
                                {"<td></td>".join(f"<td align='right'>{n}</td>"
                                                  for n in short_names)}
                            </tr>"""
            for name, (probs, curves) in self.scores:
                ind = min(np.searchsorted(probs, self.threshold),
                          len(probs) - 1)
                text += f"<tr><th align='right'>{elided(name)}:</th>"
                text += "<td>/</td>".join(f'<td>{curve[ind]:.3f}</td>'
                                          for curve in curves)
                text += "</tr>"
            text += "<table>"
            return text
        return None

    def _update_info(self):
        self.info_label.setText(self.get_info_text(short=True))

    def threshold_change_done(self):
        self.commit.deferred()

    @gui.deferred
    def commit(self):
        self.Information.no_output.clear()
        wrapped = None
        results = self.results
        if results is not None:
            problems = check_can_calibrate(
                self.results, self.selected_classifiers,
                require_binary=self.score != 0)
            if problems:
                self.Information.no_output(problems)
            else:
                clsf_idx = self.selected_classifiers[0]
                model = results.models[0, clsf_idx]
                if self.score == 0:
                    cal_learner = CalibratedLearner(
                        None, self.output_calibration)
                    wrapped = cal_learner.get_model(
                        model, results.actual, results.probabilities[clsf_idx])
                else:
                    threshold = [1 - self.threshold,
                                 self.threshold][self.target_index]
                    wrapped = ThresholdClassifier(model, threshold)

        self.Outputs.calibrated_model.send(wrapped)

    def send_report(self):
        if self.results is None:
            return
        self.report_items((
            ("目标类", self.target_cb.currentText()),
            ("输出模型校准",
             self.score == 0
             and ("Sigmoid 校准",
                  "等渗校准")[self.output_calibration])
        ))
        caption = report.list_legend(self.classifiers_list_box,
                                     self.selected_classifiers)
        self.report_plot()
        self.report_caption(caption)
        self.report_caption(self.controls.score.currentText())

        if self.score != 0:
            self.report_raw(self.get_info_text(short=False))

    def set_visual_settings(self, key, value):
        self.plot.parameter_setter.set_parameter(key, value)
        self.visual_settings[key] = value


def gaussian_smoother(x, y, sigma=1.0):
    x = np.asarray(x)
    y = np.asarray(y)

    gamma = 1. / (2 * sigma ** 2)
    a = 1. / (sigma * np.sqrt(2 * np.pi))

    if x.shape != y.shape:
        raise ValueError

    def smoother(xs):
        W = a * np.exp(-gamma * ((xs - x) ** 2))
        return np.average(y, weights=W)

    return np.vectorize(smoother, otypes=[float])


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWCalibrationPlot).run(results_for_preview())
