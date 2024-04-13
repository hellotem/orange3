from typing import NamedTuple, Dict, Type, Optional

from AnyQt.QtWidgets import QButtonGroup, QRadioButton
from AnyQt.QtCore import Qt
from scipy.sparse import issparse
import bottleneck as bn

import Orange.data
import Orange.misc
from Orange import distance
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.concurrent import TaskState, ConcurrentWidgetMixin
from Orange.widgets.utils.sql import check_sql_input
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import OWWidget, Msg, Input, Output


Euclidean, EuclideanNormalized, Manhattan, ManhattanNormalized, Cosine, \
    Mahalanobis, Hamming, \
    Pearson, PearsonAbsolute, Spearman, SpearmanAbsolute, Jaccard = range(12)


class MetricDef(NamedTuple):
    id: int  # pylint: disable=invalid-name
    name: str
    tooltip: str
    metric: Type[distance.Distance]
    normalize: bool = False


MetricDefs: Dict[int, MetricDef] = {
    metric.id: metric for metric in (
        MetricDef(EuclideanNormalized, "欧氏距离 (归一化)",
                  "归一化值差的平方和的平方根",
                  distance.Euclidean, normalize=True),
        MetricDef(Euclidean, "欧氏距离",
                  "值差的平方和的平方根",
                  distance.Euclidean),
        MetricDef(ManhattanNormalized, "曼哈顿距离 (归一化) ",
                  "归一化值绝对差之和",
                  distance.Manhattan, normalize=True),
        MetricDef(Manhattan, "曼哈顿距离",
                  "值绝对差之和",
                  distance.Manhattan),
        MetricDef(Mahalanobis, "马哈拉诺比斯距离",
                  "马哈拉诺比斯距离",
                  distance.Mahalanobis),
        MetricDef(Hamming, "汉明距离", "汉明距离",
                  distance.Hamming),
        MetricDef(Cosine, "余弦", "余弦距离",
                  distance.Cosine),
        MetricDef(Pearson, "皮尔逊相关系数",
                  "皮尔逊相关系数;距离 = 1 - ρ/2",
                  distance.PearsonR),
        MetricDef(PearsonAbsolute, "绝对皮尔逊相关系数",
                  "皮尔逊相关系数的绝对值;距离 = 1 - |ρ|",
                  distance.PearsonRAbsolute),
        MetricDef(Spearman, "斯皮尔曼相关系数",
                  "皮尔逊相关系数;距离 = 1 - ρ/2",
                  distance.PearsonR),
        MetricDef(SpearmanAbsolute, "绝对斯皮尔曼相关系数",
                  "皮尔逊相关系数的绝对值;距离 = 1 - |ρ|",
                  distance.SpearmanRAbsolute),
        MetricDef(Jaccard, "杰卡德距离", "杰卡德距离",
                  distance.Jaccard)
    )
}


class InterruptException(Exception):
    pass


class DistanceRunner:
    @staticmethod
    def run(data: Orange.data.Table, metric: distance, normalized_dist: bool,
            axis: int, state: TaskState) -> Optional[Orange.misc.DistMatrix]:
        if data is None:
            return None

        def callback(i: float) -> bool:
            state.set_progress_value(i)
            if state.is_interruption_requested():
                raise InterruptException

        state.set_status("计算中...")
        kwargs = {"axis": 1 - axis, "impute": True, "callback": callback}
        if metric.supports_normalization and normalized_dist:
            kwargs["normalize"] = True
        return metric(data, **kwargs)


class OWDistances(OWWidget, ConcurrentWidgetMixin):
    name = "距离 Distances"
    description = "计算成对距离矩阵。"
    icon = "icons/Distance.svg"
    keywords = "distances"

    class Inputs:
        data = Input("数据", Orange.data.Table)

    class Outputs:
        distances = Output("距离", Orange.misc.DistMatrix, dynamic=False)

    settings_version = 4

    axis: int = Setting(0)
    metric_id: int = Setting(EuclideanNormalized)
    autocommit: bool = Setting(True)

    want_main_area = False
    resizing_enabled = False

    class Error(OWWidget.Error):
        no_continuous_features = Msg("无数值特征")
        no_binary_features = Msg("无二值特征")
        dense_metric_sparse_data = Msg("{} 需要密集数据")
        distances_memory_error = Msg("内存不足")
        distances_value_error = Msg("计算出现问题:\n{}")
        data_too_large_for_mahalanobis = Msg(
            "Mahalanobis handles up to 1000 {}.")

    class Warning(OWWidget.Warning):
        ignoring_discrete = Msg("忽略分类特征")
        ignoring_nonbinary = Msg("忽略非二值特征")
        unsupported_sparse = Msg("有些度量不支持稀疏数据\n"
                                 "并已被禁用: {}")
        imputing_data = Msg("缺失值已被估算")

    def __init__(self):
        OWWidget.__init__(self)
        ConcurrentWidgetMixin.__init__(self)

        self.data = None

        gui.radioButtons(
            self.controlArea, self, "axis", ["行", "列"],
            box="对比", orientation=Qt.Horizontal, callback=self._invalidate
        )
        box = gui.hBox(self.controlArea, "距离度量")
        self.metric_buttons = QButtonGroup()
        width = 0
        for i, metric in enumerate(MetricDefs.values()):
            if i % 6 == 0:
                vb = gui.vBox(box)
            b = QRadioButton(metric.name)
            b.setChecked(self.metric_id == metric.id)
            b.setToolTip(metric.tooltip)
            vb.layout().addWidget(b)
            width = max(width, b.sizeHint().width())
            self.metric_buttons.addButton(b, metric.id)
        for b in self.metric_buttons.buttons():
            b.setFixedWidth(width)

        self.metric_buttons.idClicked.connect(self._metric_changed)

        gui.auto_apply(self.buttonsArea, self, "autocommit")


    @Inputs.data
    @check_sql_input
    def set_data(self, data):
        self.cancel()
        self.data = data
        self.refresh_radios()
        self.commit.now()

    def _metric_changed(self, id_):
        self.metric_id = id_
        self._invalidate()

    def refresh_radios(self):
        sparse = self.data is not None and issparse(self.data.X)
        unsupported_sparse = []
        for metric in MetricDefs.values():
            button = self.metric_buttons.button(metric.id)
            no_sparse = sparse and not metric.metric.supports_sparse
            button.setEnabled(not no_sparse)
            if no_sparse:
                unsupported_sparse.append(metric.name)
        self.Warning.unsupported_sparse(", ".join(unsupported_sparse),
                                        shown=bool(unsupported_sparse))

    @gui.deferred
    def commit(self):
        self.compute_distances(self.data)

    def compute_distances(self, data):
        def _check_sparse():
            # pylint: disable=invalid-sequence-index
            if issparse(data.X) and not metric.supports_sparse:
                self.Error.dense_metric_sparse_data(metric_def.name)
                return False
            return True

        def _fix_discrete():
            nonlocal data
            if data.domain.has_discrete_attributes() \
                    and metric is not distance.Jaccard \
                    and (issparse(data.X) and getattr(metric, "fallback", None)
                         or not metric.supports_discrete
                         or self.axis == 1):
                if not data.domain.has_continuous_attributes():
                    self.Error.no_continuous_features()
                    return False
                self.Warning.ignoring_discrete()
                data = distance.remove_discrete_features(data, to_metas=True)
            return True

        def _fix_nonbinary():
            nonlocal data
            if metric is distance.Jaccard and not issparse(data.X):
                nbinary = sum(a.is_discrete and len(a.values) == 2
                              for a in data.domain.attributes)
                if not nbinary:
                    self.Error.no_binary_features()
                    return False
                elif nbinary < len(data.domain.attributes):
                    self.Warning.ignoring_nonbinary()
                    data = distance.remove_nonbinary_features(data,
                                                              to_metas=True)
            return True

        def _fix_missing():
            nonlocal data
            if not metric.supports_missing and bn.anynan(data.X):
                self.Warning.imputing_data()
                data = distance.impute(data)
            return True

        def _check_tractability():
            if metric is distance.Mahalanobis:
                if self.axis == 0:
                    # when computing distances by columns, we want < 1000 rows
                    if len(data) > 1000:
                        self.Error.data_too_large_for_mahalanobis("行")
                        return False
                else:
                    if len(data.domain.attributes) > 1000:
                        self.Error.data_too_large_for_mahalanobis("列")
                        return False
            return True

        metric_def = MetricDefs[self.metric_id]
        metric = metric_def.metric
        self.clear_messages()
        if data is not None:
            for check in (_check_sparse, _check_tractability,
                          _fix_discrete, _fix_missing, _fix_nonbinary):
                if not check():
                    data = None
                    break

        self.start(DistanceRunner.run, data, metric,
                   metric_def.normalize, self.axis)

    def on_partial_result(self, _):
        pass

    def on_done(self, result: Orange.misc.DistMatrix):
        assert isinstance(result, Orange.misc.DistMatrix) or result is None
        self.Outputs.distances.send(result)

    def on_exception(self, ex):
        if isinstance(ex, ValueError):
            self.Error.distances_value_error(ex)
        elif isinstance(ex, MemoryError):
            self.Error.distances_memory_error()
        elif isinstance(ex, InterruptException):
            pass
        else:
            raise ex

    def onDeleteWidget(self):
        self.shutdown()
        super().onDeleteWidget()

    def _invalidate(self):
        self.commit.deferred()

    def send_report(self):
        # pylint: disable=invalid-sequence-index
        self.report_items((
            ("距离对象", ["行", "列 "][self.axis]),
            ("度量", MetricDefs[self.metric_id].name)
        ))

    @classmethod
    def migrate_settings(cls, settings, version):
        if version is None or version < 2 and "normalized_dist" not in settings:
            # normalize_dist is set to False when restoring settings from
            # an older version to preserve old semantics.
            settings["normalized_dist"] = False
        if version is None or version < 3:
            # Mahalanobis was moved from idx = 2 to idx = 9
            metric_idx = settings["metric_idx"]
            if metric_idx == 2:
                settings["metric_idx"] = 9
            elif 2 < metric_idx <= 9:
                settings["metric_idx"] -= 1
        if version < 4:
            metric_idx = settings.pop("metric_idx")
            metric_id = [Euclidean, Manhattan, Cosine, Jaccard,
                         Spearman, SpearmanAbsolute, Pearson, PearsonAbsolute,
                         Hamming, Mahalanobis, Euclidean][metric_idx]
            if settings.pop("normalized_dist", False):
                metric_id = {Euclidean: EuclideanNormalized,
                             Manhattan: ManhattanNormalized}.get(metric_id,
                                                                 metric_id)
            settings["metric_id"] = metric_id


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWDistances).run(Orange.data.Table("iris"))
