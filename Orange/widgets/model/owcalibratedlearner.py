from Orange.classification import CalibratedLearner, ThresholdLearner, \
    NaiveBayesLearner
from Orange.data import Table
from Orange.modelling import Learner
from Orange.widgets import gui
from Orange.widgets.widget import Input
from Orange.widgets.settings import Setting
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWCalibratedLearner(OWBaseLearner):
    name = "校准学习器 Calibrated Learner"
    description = "用概率校准和" \
                  "决策阈值优化包装另一学习器"
    icon = "icons/CalibratedLearner.svg"
    priority = 20
    keywords = "校准学习器、校准、阈值"

    LEARNER = CalibratedLearner

    SigmoidCalibration, IsotonicCalibration, NoCalibration = range(3)
    CalibrationOptions = ("Sigmoid校准",
                          "等渗校准",
                          "无校准")
    CalibrationShort = ("Sigmoid", "等渗", "")
    CalibrationMap = {
        SigmoidCalibration: CalibratedLearner.Sigmoid,
        IsotonicCalibration: CalibratedLearner.Isotonic}

    OptimizeCA, OptimizeF1, NoThresholdOptimization = range(3)
    ThresholdOptions = ("优化分类准确率",
                        "优化F1分数",
                        "无阈值优化")
    ThresholdShort = ("分类准确率", "F1", "")
    ThresholdMap = {
        OptimizeCA: ThresholdLearner.OptimizeCA,
        OptimizeF1: ThresholdLearner.OptimizeF1}

    learner_name = Setting("", schema_only=True)
    calibration = Setting(SigmoidCalibration)
    threshold = Setting(OptimizeCA)

    class Inputs(OWBaseLearner.Inputs):
        base_learner = Input("基学习器", Learner)

    def __init__(self):
        super().__init__()
        self.base_learner = None

    def add_main_layout(self):
        gui.radioButtons(
            self.controlArea, self, "calibration", self.CalibrationOptions,
            box="概率校准",
            callback=self.calibration_options_changed)
        gui.radioButtons(
            self.controlArea, self, "threshold", self.ThresholdOptions,
            box="决策阈值优化",
            callback=self.calibration_options_changed)

    @Inputs.base_learner
    def set_learner(self, learner):
        self.base_learner = learner
        self._set_default_name()
        self.learner = self.model = None

    def _set_default_name(self):

        if self.base_learner is None:
            self.set_default_learner_name("")
        else:
            name = " + ".join(part for part in (
                self.base_learner.name.title(),
                self.CalibrationShort[self.calibration],
                self.ThresholdShort[self.threshold]) if part)
            self.set_default_learner_name(name)

    def calibration_options_changed(self):
        self._set_default_name()
        self.apply()

    def create_learner(self):
        class IdentityWrapper(Learner):
            def fit_storage(self, data):
                return self.base_learner.fit_storage(data)

        if self.base_learner is None:
            return None
        learner = self.base_learner
        if self.calibration != self.NoCalibration:
            learner = CalibratedLearner(learner,
                                        self.CalibrationMap[self.calibration])
        if self.threshold != self.NoThresholdOptimization:
            learner = ThresholdLearner(learner,
                                       self.ThresholdMap[self.threshold])
        if self.preprocessors:
            if learner is self.base_learner:
                learner = IdentityWrapper()
            learner.preprocessors = (self.preprocessors, )
        return learner

    def get_learner_parameters(self):
        return (("校准概率",
                 self.CalibrationOptions[self.calibration]),
                ("阈值优化",
                 self.ThresholdOptions[self.threshold]))


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWCalibratedLearner).run(
        Table("heart_disease"),
        set_learner=NaiveBayesLearner())
